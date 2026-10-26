# Symbiosis Algorithm Trading (V8.0)
### Laboratoire Quantitatif Multi-Agents, Machine Learning & Intelligence en Essaim

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Scikit-Learn](https://img.shields.io/badge/ML-GradientBoosting-orange?logo=scikit-learn&logoColor=white)
![CCXT](https://img.shields.io/badge/Market_Data-CCXT_%26_yFinance-success)
![Discord](https://img.shields.io/badge/Interface-Discord.py-5865F2?logo=discord&logoColor=white)
![Status](https://img.shields.io/badge/Version-8.0_(100_Agents)-purple)

**Symbiosis Algorithm Trading** est un laboratoire spéculatif automatisé qui fait s'affronter en temps réel **100 robots de trading autonomes** sur 6 marchés financiers (**Bitcoin, Solana, Or, Argent, Platine, Pétrole WTI**). 

Conçu pour étudier empiriquement la sélection naturelle des stratégies, l'impact des coûts de friction et la supériorité du consensus de foule (*Swarm Intelligence*) sur les algorithmes isolés, le système tourne 24/7 avec une interface de contrôle interactive sur Discord.

---

## Architecture de l'Écosystème (V8.0 — 100 Bots)

Plutôt que de chercher un « indicateur miracle », **Symbiosis** divise ses 100 agents en **7 familles évolutives** soumises aux mêmes règles strictes de gestion du risque et de coûts de transaction réels (Frais Maker/Taker, Spread, Slippage, Funding Rate journalier) :

| Famille | Nombre | Logique Quantitative & Comportement |
| :--- | :---: | :--- |
| **1. Confirmation (`_Confirm`)** | 22 | Suivi de tendance multi-timeframe (EMA 50/200 1h + Momentum 5m), cassures de nuage **Ichimoku**, **Vrai Supertrend** et flux de volume **OBV**. |
| **2. Retournement (`_Retourn`)** | 18 | Stratégies de retour à la moyenne (*Mean Reversion*) : excès **RSI / Williams %R**, rebonds sur **VWAP journalier**, bandes de Bollinger et divergences Prix/OBV. |
| **3. Caméléons (`_Cameleon`)** | 15 | **Détection de régime dynamique via l'ADX (14)** : basculent automatiquement en mode *Confirmation* lorsque le marché est directionnel ($\text{ADX} \ge 25$) et en mode *Retournement* en marché de range ($\text{ADX} < 25$). |
| **4. Machine Learning (`_ML`)** | 15 | Pilotés par un moteur **`GradientBoostingClassifier`** (Scikit-Learn) ré-entraîné toutes les 6h sur 12 features techniques avec seuils de labellisation dynamiques basés sur la volatilité ($\pm 0.85 \times \text{ATR}_{5\text{m}}$). |
| **5. Auto-Adaptatifs (`_RL`)** | 15 | **Apprentissage par renforcement en ligne (*Online Policy Gradient*)** : après chaque trade clôturé, le bot augmente le poids des indicateurs ayant généré un profit et pénalise ceux ayant induit une perte. |
| **6. Méta-Essaim (`_Meta`)** | 12 | **Intelligence collective (Incubation de 14 jours)** : analysent en Passe 2 les positions des autres agents pour suivre le consensus du Top 10 (`Crowd_Top10`) ou prendre l'exact opposé des 5 pires bots (`Fade_Bottom5`). |
| **7. Témoins (`_Temoin`)** | 3 | Groupe de contrôle scientifique : `Singe_Aleatoire` (bruit pur), `Le_Permabull` (100% Long) et `Le_Permabear` (100% Short). |

---

## Enseignements Quantitatifs (6 mois d'historique live)

L'itération de la V1 à la V8.0 sur données réelles a mis en évidence trois phénomènes majeurs :

1. **La friction élimine la sur-activité :** Avec l'intégration du spread, du slippage et du *funding rate*, les stratégies à haute fréquence sans filtre de volatilité convergent vers l'espérance mathématique du bot `Singe_Aleatoire`.
2. **Le paradoxe de précision en Machine Learning financier :** Un classifieur utilisant un seuil fixe ($\pm 0.30\%$) sur un actif peu volatil comme l'Or atteint 85 % de précision en prédisant la classe majoritaire « Neutre » 96 % du temps. La V8.0 résout ce biais via une labellisation indexée sur l'ATR et une pondération équilibrée des classes (`sample_weight='balanced'`).
3. **L'émergence de l'Alpha par le Consensus du Top 10 :** Lorsqu'au moins **6 des 10 meilleurs bots du classement général** ouvrent une position dans la même direction simultanément, le filtrage croisé (Macro + Micro + Volume + ML) réduit drastiquement les faux signaux.

---

## Moteur Financier & Gestion du Risque

* **Position Sizing par Demi-Critère de Kelly :** Pour les agents adaptatifs et ML, la fraction du capital engagée est ajustée dynamiquement selon l'espérance mathématique réelle :
  $$f^* = \frac{1}{2} \left( p - \frac{1 - p}{b} \right)$$
  où $p$ est le *Winrate* historique du bot et $b = 2.0$ le ratio *Risk/Reward* ($\text{TP} = 4.0 \times \text{ATR}$, $\text{SL} = 2.0 \times \text{ATR}$).
* **Trailing Stop Dynamique indexé sur l'ATR :** Activation d'un stop suiveur à $1.8 \times \text{ATR}$ uniquement après franchissement d'un seuil de rentabilité de $+1.2 \times \text{ATR}$.
* **Analyse de Sentiment NLP :** Agrégation temps réel des dépêches **Finnhub** et flux RSS financiers évalués via le modèle lexical **VADER**.

---

## Commandes Principales (Interface Discord)

* `!sniper` : Tableau de bord interactif par actif (Prix, ATR, Régime ADX, Indicateurs, Sentiment News).
* `!lb` : Classement général paginé des 100 bots et du joueur humain (Capital, PnL %, Winrate, Frais payés).
* `!portfolio` : Focus sur le Top 10 actuel de l'écosystème.
* `!ml` : Métriques de validation des 6 modèles `GradientBoosting` (Accuracy Train/Val, distribution des labels, Top Features).
* `!rl` : Inspection en direct de la mutation des poids des 15 bots Auto-Adaptatifs.
* `!chasse` : Suivi de la période d'incubation de 14 jours et des cibles des Méta-Bots (`Crowd_Top10` & `Fade_Bottom5`).
* `!buy <actif>` / `!sell <actif>` / `!mypos` : Permet à un opérateur humain de concourir dans le classement avec les mêmes règles de friction que les bots.

---
