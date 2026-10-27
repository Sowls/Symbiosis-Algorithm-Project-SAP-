# Symbiosis Algorithm Trading (V8.6)
### Laboratoire Quantitatif Multi-Agents, Machine Learning & Intelligence en Essaim

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Scikit-Learn](https://img.shields.io/badge/ML-GradientBoosting-orange?logo=scikit-learn&logoColor=white)
![CCXT](https://img.shields.io/badge/Market_Data-CCXT_%26_yFinance-success)
![Discord](https://img.shields.io/badge/Interface-Discord.py-5865F2?logo=discord&logoColor=white)
![Status](https://img.shields.io/badge/Version-8.6_(100_Agents)-purple)
![License](https://img.shields.io/badge/License-MIT-green)

**Symbiosis Algorithm Trading** est un laboratoire spéculatif automatisé faisant s'affronter en temps réel **100 robots de trading autonomes** sur 6 marchés (**Bitcoin, Solana, Or, Argent, Platine, Pétrole WTI**).

Initialement né d'un projet de recherche en classe préparatoire (2024), l'écosystème a évolué sur 4 générations pour étudier empiriquement la sélection naturelle des stratégies, la rentabilité nette après friction réelle (Frais Maker/Taker, Spread, Slippage, Funding Rates) et l'émergence d'alpha via l'intelligence collective (*Swarm Intelligence*).

---

## Architecture d'Exécution & Verrous Quantitatifs (V8.6)

La version V8.6 introduit un calibrage strict orienté sur la sélectivité des entrées et la protection du capital :

1. **Cadence de Scan 10m, Seuil 65 % & Horizon Cible (1h – 1h30) :**  
   L'analyse micro-structurelle sur bougies 5m est exécutée toutes les **10 minutes** avec un seuil d'entrée rehaussé à **65 % de conviction** (`SIGNAL_THRESHOLD = 65`) et une limite de **2 positions simultanées maximum** par agent. Les distances d'objectifs sont calibrées sur la volatilité pour un dénouement rapide :
   * **TP1 (+1,8*ATR, atteint en ~25–35 min) :** Encaissement automatique de **50 % de la position** en banque (victoire validée) et déplacement immédiat du Stop-Loss au **Break-Even** (prix d'entrée + frais couverts).
   * **TP2 Final (+3,8*ATR, atteint en ~1h00–1h30) :** Clôture des 50 % restants ou sortie sur Trailing Stop dynamique (1,6*ATR).
2. **Détecteur d'Anticipation de Choc (`shock_anticipation`) & Double Filtrage :**  
   * **Filtre d'Incertitude & Non-Contradiction :** Pénalise les marchés sans direction (ADX < 20) et bloque les entrées en suivi de tendance lorsque le momentum court terme (`MACD 5m`) et le flux de volume (`OBV`) s'opposent simultanément.
   * **Clause Disjoncteur (Chocs Imminents) :** Lorsqu'une anomalie de marché survient (volume *Baleine*, sortie de compression *Squeeze*, balayage de liquidité *Stop-Hunt* ou divergence brutale Prix/OBV), les filtres d'incertitude s'effacent automatiquement pour permettre aux agents d'anticiper les décrochages ou explosions avant le retournement des moyennes mobiles 1h.
3. **Bouclier Anti-Gap & Protection Week-end (Futures) :**
   * **Vendredi dès 19h00 UTC :** Gel préventif total des nouvelles ouvertures sur les métaux précieux et le pétrole.
   * **Vendredi entre 21h00 et 21h59 UTC :** Clôture préventive des positions Futures récentes, en perte ou proches du Break-Even. Les positions très gagnantes voient leur Stop-Loss verrouillé au Break-Even pour passer le week-end sans risque.
   * **Dimanche 22h00 – 23h00 UTC :** Gel des entrées pendant la première heure de réouverture (protection contre les spreads élargis).
4. **Filtre Anti-Couteau qui tombe & Cooldown (30 min) :**  
   Validation de bougie obligatoire (mèche de rejet, ou clôture dans le sens du rebond) pour les stratégies contrariennes, couplée à une pause forcée de **30 minutes** sur un actif après un Stop-Loss.

---

## Les 7 Familles de l'Écosystème (100 Agents)

| Famille | Quota | Logique & Spécialisations Clés |
| :--- | :---: | :--- |
| **1. Confirmation (`_Confirm`)** | 22 | Inclut le champion historique **`Kelly_Optimizer_V7_Confirm`** et **`Opti_Data_Driven_Confirm`**, le suivi multi-timeframe (EMA 50/200 1h + 5m), **Ichimoku**, **Vrai Supertrend**, ainsi que les modules **`_Pullback`** (replis 5m dans tendance 1h), **`_Squeeze`** (compressions Bollinger/Keltner) et **`_Killzone`** (sessions Londres 08h-11h & NY 13h-16h UTC). |
| **2. Retournement (`_Retourn`)** | 18 | Exploitation statistique des excès : rebonds **VWAP journalier**, bandes de Bollinger, divergences Prix/OBV et modules **`_StopHunt`** (chasseurs de liquidités après balayage des plus hauts/bas de 20 bougies). |
| **3. Caméléons (`_Cameleon`)** | 15 | **Détection de régime par l'ADX (14)** : bascule dynamique et instantanée entre les moteurs *Confirmation* et *Retournement*. |
| **4. Machine Learning (`_ML`)** | 15 | Pilotés par un classifieur **`GradientBoostingClassifier`** (`max_depth=3`, classes équilibrées) ré-entraîné toutes les 6h sur 12 variables quantitatives avec seuil dynamique indexé sur l'ATR. |
| **5. Auto-Adaptatifs (`_RL`)** | 15 | **Apprentissage par renforcement en ligne (*Policy Gradient*)** : réajustement des poids après chaque trade. Intègre des modules **`_AutoThresh`** (seuil d'exigence auto-ajusté entre 60 % et 82 %) et **`_Specialist`** (mémoire de rentabilité par actif). |
| **6. Méta-Essaim (`_Meta`)** | 12 | **Intelligence collective (Incubation stricte de 14 jours)** : analysent les positions du groupe pour suivre le consensus du Top 10 (`Crowd_Top10`) ou prendre l'exact contre-pied des 5 pires bots (`Fade_Bottom5`). |
| **7. Témoins (`_Temoin`)** | 3 | Groupe de contrôle scientifique : `Singe_Aleatoire` (bruit pur), `Le_Permabull` (100 % Long) et `Le_Permabear` (100 % Short). |

---

## ⚙️ Moteur Financier & Modélisation du Risque

* **Position Sizing par Demi-Critère de Kelly :**  
  Pour les agents adaptatifs et ML, le capital engagé est modulé en fonction du winrate réel p et du ratio Risk/Reward b = 1,8 :
  $$f^* = \frac{1}{2} \left( p - \frac{1 - p}{b} \right)$$
  Borné entre 12 % et 35 % du capital pour éviter le risque de ruine.
* **Capital Virtuel Négatif Protégé :**  
  Les bots perdants peuvent continuer de descendre dans le négatif comptable sans bloquer le moteur, afin d'alimenter en continu les stratégies contrariennes (`Fade_Bottom5`). Leur assiette de calcul de marge reste planchée à $100\,\$$ pour préserver l'intégrité mathématique des tailles de position.
* **Prise en Compte des Coûts Réels :**  
  Intégration systématique des frais Maker (`0,02 %`), du slippage/spread (`0,08 %`) et du *funding rate* journalier (`0,06 %`) décompté au prorata temporis.

---

## Commandes Discord V8.6

* `!sniper` : Terminal d'analyse temps réel avec sélection par boutons (Prix, ATR %, Régime ADX, Détecteur de Choc, Score `Kelly_Optimizer_V7`, Consensus des Familles, Score ML).
* `!marches` : État d'ouverture des 6 marchés, statut du **Bouclier Vendredi Soir** et cadence du scanner (10m).
* `!chasse` : Compte à rebours de l'incubation de 14 jours et cibles actives des Méta-Bots (`Crowd_Top10` et `Fade_Bottom5`).
* `!lb` : Classement général paginé (100 bots + joueur humain) avec PnL %, Winrate et cumul des frais payés.
* `!portfolio` : Focus sur les 10 meilleurs bots actuels de l'écosystème.
* `!ml` : Diagnostic des modèles d'arbres GradientBoosting par actif (Accuracy Train/Val, balance des classes, top features).
* `!rl` : Inspection des coefficients et seuils d'entrée (60 %–82 %) appris par les 15 agents auto-adaptatifs.
* `!allpos` : Liste détaillée des positions actives (avec mention du statut `✅TP1` atteint).
* `!buy <actif>` / `!sell <actif>` / `!mypos` : Interface de trading manuel permettant à l'utilisateur de concourir dans les mêmes conditions d'exécution.

---
## Disclaimer 

Ce logiciel est un laboratoire de recherche en finance quantitative, data science et modélisation multi-agents à vocation strictement expérimentale et éducative (Paper Trading). Les signaux et statistiques générés ne constituent en aucun cas des conseils financiers ou des incitations à l'investissement sur des fonds réels.
Merci de me demander pour toute reproduction, contribution ou utilisation. 
Usage à des fins commerciales interdit. 


~ Rémy Mahé

