"""
ml_engine.py — Module Machine Learning Quantitatif V8.5 (Symbiosis)
- Alignement strict des features Train/Live (5m).
- Labellisation dynamique indexée sur l'ATR (élimine le biais 'Neutre').
- Pondération équilibrée des classes (sample_weight='balanced').
"""

import time
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight
import warnings
warnings.filterwarnings('ignore', category=UserWarning)


class MLEngine:
    RETRAIN_INTERVAL = 6 * 3600   # 6 heures
    PREDICTION_HORIZON = 6        # +6 bougies (30 min en 5m TF)
    ATR_LABEL_MULT = 0.85         # Seuil dynamique = 0.85 * ATR_5m
    MIN_SAMPLES = 250

    FEATURE_NAMES = [
        'rsi_14', 'macd_hist_norm', 'ema_diff_pct', 'bb_position',
        'stoch_k', 'atr_pct', 'volume_ratio', 'price_change_5',
        'price_change_20', 'hour_sin', 'hour_cos', 'adx',
    ]

    def __init__(self):
        self.models = {}
        self.scalers = {}
        self.last_train = {}
        self.accuracy = {}
        self.train_accuracy = {}
        self.samples_train = {}
        self.samples_val = {}
        self.label_distribution = {}
        self.feature_importance = {}
        self.is_training = {}

    def _extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = pd.DataFrame(index=df.index)

        # 1. RSI 14
        delta = df['Close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(com=13, adjust=False).mean()
        ema_down = down.ewm(com=13, adjust=False).mean()
        features['rsi_14'] = 100 - (100 / (1 + ema_up / ema_down.replace(0, 1e-9)))

        # 2. MACD histogram normalisé
        macd_line = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - signal_line
        macd_range = macd_hist.abs().rolling(50).max().replace(0, 1e-9)
        features['macd_hist_norm'] = (macd_hist / macd_range).clip(-1, 1)

        # 3. EMA diff % (EMA50 vs EMA200 5m)
        ema50 = df['Close'].ewm(span=50, adjust=False).mean()
        ema200 = df['Close'].ewm(span=200, adjust=False).mean()
        features['ema_diff_pct'] = ((ema50 - ema200) / ema200.replace(0, 1e-9) * 100).clip(-5, 5)

        # 4. Bollinger position [0, 1]
        sma20 = df['Close'].rolling(20).mean()
        std20 = df['Close'].rolling(20).std()
        bb_lower = sma20 - 2 * std20
        bb_upper = sma20 + 2 * std20
        bb_range = (bb_upper - bb_lower).replace(0, 1e-9)
        features['bb_position'] = ((df['Close'] - bb_lower) / bb_range).clip(0, 1)

        # 5. Stochastique K
        l14 = df['Low'].rolling(14).min()
        h14 = df['High'].rolling(14).max()
        h14_range = (h14 - l14).replace(0, 1e-9)
        features['stoch_k'] = (100 * (df['Close'] - l14) / h14_range).rolling(3).mean()

        # 6. ATR %
        hl = df['High'] - df['Low']
        hc = (df['High'] - df['Close'].shift()).abs()
        lc = (df['Low'] - df['Close'].shift()).abs()
        atr = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()
        features['atr_pct'] = (atr / df['Close'].replace(0, 1e-9) * 100).clip(0, 20)

        # 7. Volume ratio
        vol_sma = df['Volume'].rolling(20).mean().replace(0, 1e-9)
        features['volume_ratio'] = (df['Volume'] / vol_sma).clip(0, 10)

        # 8 & 9. Price changes
        features['price_change_5'] = df['Close'].pct_change(5) * 100
        features['price_change_20'] = df['Close'].pct_change(20) * 100

        # 10 & 11. Heure cyclique
        if 'Datetime' in df.columns:
            hours = pd.to_datetime(df['Datetime'], unit='ms', errors='coerce').dt.hour.fillna(12)
        elif hasattr(df.index, 'hour'):
            hours = pd.Series(df.index.hour, index=df.index)
        else:
            hours = pd.Series(12, index=df.index)
        features['hour_sin'] = np.sin(2 * np.pi * hours / 24)
        features['hour_cos'] = np.cos(2 * np.pi * hours / 24)

        # 12. ADX (14)
        plus_dm = df['High'].diff().clip(lower=0)
        minus_dm = (-df['Low'].diff()).clip(lower=0)
        plus_dm = plus_dm.where(plus_dm > minus_dm, 0)
        minus_dm = minus_dm.where(minus_dm > plus_dm, 0)
        atr_safe = atr.replace(0, 1e-9)
        plus_di = 100 * (plus_dm.ewm(span=14, adjust=False).mean() / atr_safe)
        minus_di = 100 * (minus_dm.ewm(span=14, adjust=False).mean() / atr_safe)
        di_sum = (plus_di + minus_di).replace(0, 1e-9)
        dx = (abs(plus_di - minus_di) / di_sum) * 100
        features['adx'] = dx.ewm(span=14, adjust=False).mean()

        return features

    def _create_labels(self, df: pd.DataFrame, atr_pct_series: pd.Series) -> pd.Series:
        future_return_pct = (df['Close'].shift(-self.PREDICTION_HORIZON) / df['Close'] - 1) * 100
        dyn_threshold = (atr_pct_series * self.ATR_LABEL_MULT).clip(lower=0.08, upper=1.50)

        labels = pd.Series(0, index=df.index)
        labels[future_return_pct > dyn_threshold] = 1
        labels[future_return_pct < -dyn_threshold] = -1
        return labels

    def extract_latest_feature_dict(self, df: pd.DataFrame) -> dict:
        feats = self._extract_features(df).ffill().bfill()
        if feats.empty:
            return {k: 0.0 for k in self.FEATURE_NAMES}
        last_row = feats.iloc[-1]
        return {k: float(last_row.get(k, 0.0)) for k in self.FEATURE_NAMES}

    def train(self, asset_name: str, df: pd.DataFrame) -> dict:
        if self.is_training.get(asset_name, False):
            return {'status': 'already_training'}

        self.is_training[asset_name] = True
        try:
            if len(df) < self.MIN_SAMPLES:
                return {'status': 'insufficient_data', 'rows': len(df)}

            features = self._extract_features(df)
            labels = self._create_labels(df, features['atr_pct'])

            combined = features.copy()
            combined['label'] = labels
            combined = combined.dropna()
            combined = combined.iloc[:-self.PREDICTION_HORIZON]

            if len(combined) < 120:
                return {'status': 'insufficient_clean_data', 'rows': len(combined)}

            X = combined[self.FEATURE_NAMES].values
            y = combined['label'].values

            split_idx = int(len(X) * 0.8)
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]

            if len(np.unique(y_train)) < 2:
                return {'status': 'single_class_error'}

            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_val_scaled = scaler.transform(X_val)

            sample_weights = compute_sample_weight(class_weight='balanced', y=y_train)

            model = GradientBoostingClassifier(
                n_estimators=80,
                max_depth=3,
                learning_rate=0.05,
                subsample=0.8,
                min_samples_leaf=20,
                random_state=42
            )
            model.fit(X_train_scaled, y_train, sample_weight=sample_weights)

            val_accuracy = model.score(X_val_scaled, y_val)
            train_accuracy = model.score(X_train_scaled, y_train)

            unique, counts = np.unique(y_train, return_counts=True)
            label_dist = dict(zip(unique.astype(int), counts.astype(int)))

            if val_accuracy > 0.34:
                self.models[asset_name] = model
                self.scalers[asset_name] = scaler
                self.accuracy[asset_name] = val_accuracy
                self.last_train[asset_name] = time.time()
                self.train_accuracy[asset_name] = train_accuracy
                self.samples_train[asset_name] = len(X_train)
                self.samples_val[asset_name] = len(X_val)
                self.label_distribution[asset_name] = label_dist
                self.feature_importance[asset_name] = dict(zip(
                    self.FEATURE_NAMES,
                    [round(float(x), 4) for x in model.feature_importances_]
                ))
                status = 'success'
            else:
                status = 'accuracy_too_low'

            print(f"🧠 ML [{asset_name}] {status} | Val: {val_accuracy:.2%} (Train: {train_accuracy:.2%}) | Samples: {len(X_train)}")
            return {'status': status, 'val_accuracy': val_accuracy}

        except Exception as e:
            print(f"❌ ML train error [{asset_name}]: {type(e).__name__}: {e}")
            return {'status': 'error', 'error': str(e)}
        finally:
            self.is_training[asset_name] = False

    def predict(self, asset_name: str, features_dict: dict) -> float:
        if asset_name not in self.models:
            return 0.0
        try:
            feature_values = []
            for fname in self.FEATURE_NAMES:
                val = features_dict.get(fname, 0.0)
                if pd.isna(val) or np.isinf(val):
                    val = 0.0
                feature_values.append(float(val))

            X = np.array([feature_values])
            X_scaled = self.scalers[asset_name].transform(X)

            model = self.models[asset_name]
            probas = model.predict_proba(X_scaled)[0]
            classes = model.classes_

            prob_up, prob_down = 0.0, 0.0
            for cls, prob in zip(classes, probas):
                if cls == 1:
                    prob_up = prob
                elif cls == -1:
                    prob_down = prob

            raw_diff = (prob_up - prob_down) * 1.35
            return max(-1.0, min(1.0, float(raw_diff)))

        except Exception as e:
            print(f"⚠️ ML predict error [{asset_name}]: {type(e).__name__}: {e}")
            return 0.0

    def needs_retrain(self, asset_name: str) -> bool:
        last = self.last_train.get(asset_name, 0)
        return (time.time() - last) > self.RETRAIN_INTERVAL

    def get_status(self) -> dict:
        status = {}
        for asset in ['Bitcoin', 'Solana', 'Or', 'Platine', 'Crude Oil', 'Argent']:
            trained = asset in self.models
            last = self.last_train.get(asset, 0)
            age_h = (time.time() - last) / 3600 if last > 0 else -1
            status[asset] = {
                'trained': trained,
                'accuracy': self.accuracy.get(asset, 0.0),
                'train_accuracy': self.train_accuracy.get(asset, 0.0),
                'samples_train': self.samples_train.get(asset, 0),
                'samples_val': self.samples_val.get(asset, 0),
                'label_distribution': self.label_distribution.get(asset, {}),
                'feature_importance': self.feature_importance.get(asset, {}),
                'age_hours': round(age_h, 1),
                'needs_retrain': self.needs_retrain(asset)
            }
        return status


ml_engine = MLEngine()
