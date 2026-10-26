# Symbiosis Algorithm Trading (V8.5)
### Laboratoire Quantitatif Multi-Agents, Machine Learning & Intelligence en Essaim

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Scikit-Learn](https://img.shields.io/badge/ML-GradientBoosting-orange?logo=scikit-learn&logoColor=white)
![CCXT](https://img.shields.io/badge/Market_Data-CCXT_%26_yFinance-success)
![Discord](https://img.shields.io/badge/Interface-Discord.py-5865F2?logo=discord&logoColor=white)
![Status](https://img.shields.io/badge/Version-8.5_(100_Agents)-purple)
![License](https://img.shields.io/badge/License-MIT-green)

**Symbiosis Algorithm Trading** est un laboratoire spéculatif automatisé faisant s'affronter en temps réel **100 robots de trading autonomes** sur 6 marchés (**Bitcoin, Solana, Or, Argent, Platine, Pétrole WTI**).

Initialement né d'un projet de recherche en classe préparatoire (2024), l'écosystème a évolué sur 4 générations pour étudier empiriquement la sélection naturelle des stratégies, la rentabilité nette après friction réelle (Frais Maker/Taker, Spread, Slippage, Funding Rates) et l'émergence d'alpha via l'intelligence collective (*Swarm Intelligence*).

---

## Nouveautés Majeures de la Version V8.5

La version V8.5 résout le plafond de rentabilité des versions précédentes grâce à 5 verrous structurels :

1. **Prise de profit partielle TP1 (50 % à $+1,8 \times \text{ATR}$) + Break-Even automatique :**  
   Dès que le trade atteint $+1,8 \times \text{ATR}$, le bot encaisse immédiatement la moitié de sa position en banque (victoire validée) et remonte son Stop-Loss au prix d'entrée majoré des frais. Les 50 % restants surfent la tendance jusqu'au TP2 ($+3,8 \times \text{ATR}$) ou sortent en trailing stop. **Il devient mathématiquement impossible de perdre sur un trade ayant atteint le TP1.**
2. **Bouclier Anti-Gap & Protection Week-end (Futures) :**
   * **Vendredi dès 19h00 UTC :** Gel préventif total des ouvertures sur les métaux précieux et le pétrole.
   * **Vendredi entre 21h00 et 21h59 UTC :** Clôture d'urgence de toutes les positions Futures récentes, en perte ou proches du Break-Even ($< +1,5 \times \text{ATR}$) pour éviter le risque de saut de cotation (Gap) du week-end. Les positions largement gagnantes ($ge +1,5 \times \text{ATR}$) voient leur Stop-Loss verrouillé au Break-Even.
   * **Dimanche 22h00 – 23h00 UTC :** Blocage des entrées pendant la première heure de réouverture pour se prémunir des spreads anormaux.
3. **Filtre Anti-Couteau qui tombe (Validation de Bougie) :**  
   Les stratégies de retournement n'entrent plus à l'aveugle sur simple survente RSI : une validation visuelle sur la bougie 5m (mèche de rejet $\ge 45\,\%$ ou clôture dans le sens du rebond) est désormais requise.
4. **Cooldown Anti-Revenge Trading (30 minutes) :**  
   Après le déclenchement d'un Stop-Loss sur un actif, l'agent subit une mise en pause forcée de 30 minutes sur ce marché pour éliminer l'acharnement sur fausse cassure.
5. **Suppression du `logic_exit` prématuré :**  
   Les positions ne sont plus coupées sur de simples respirations contraires de court terme ; seules les invalidations extrêmes ($\ge 80\,\%$) ou les Stop-Loss clôturent le solde.

---

## Architecture de l'Écosystème (100 Agents)

Les 100 bots sont répartis en **7 familles complémentaires**, enrichies de nouveaux archétypes spécialisés :

| Famille | Quota | Logique & Spécialisations Clés |
| :--- | :---: | :--- |
| **1. Confirmation (`_Confirm`)** | 22 | Suivi de tendance multi-timeframe (EMA 50/200 1h + Momentum 5m), cassures **Ichimoku**, **Vrai Supertrend**, flux **OBV**, ainsi que les nouveaux modules **`_Pullback`** (achats sur replis 5m alignés 1h), **`_Squeeze`** (compressions Bollinger/Keltner) et **`_Killzone`** (sessions Londres/NY). |
| **2. Retournement (`_Retourn`)** | 18 | Exploitation statistique des excès : rebonds **VWAP journalier**, bandes de Bollinger, divergences Prix/OBV et nouveaux modules **`_StopHunt`** (chasseurs de liquidités après balayage de mèches). |
| **3. Caméléons (`_Cameleon`)** | 15 | **Détection de régime par l'ADX (14)** : bascule dynamique et instantanée entre les moteurs *Confirmation* ($\text{ADX} \ge 25$) et *Retournement* ($\text{ADX} < 25$). |
| **4. Machine Learning (`_ML`)** | 15 | Pilotés par un classifieur **`GradientBoostingClassifier`** ré-entraîné toutes les 6h sur 12 variables quantitatives, avec seuil dynamique basé sur l'ATR ($\pm 0,85 \times \text{ATR}_{5\text{m}}$). |
| **5. Auto-Adaptatifs (`_RL`)** | 15 | **Apprentissage par renforcement en ligne (*Policy Gradient*)** : réajustement des poids après chaque trade. Intègre des modules **`_AutoThresh`** (sélectivité haussière après perte) et **`_Specialist`** (mémoire de rentabilité par actif). |
| **6. Méta-Essaim (`_Meta`)** | 12 | **Intelligence collective (Incubation stricte de 14 jours)** : analysent les positions du groupe pour suivre le consensus du Top 10 (`Crowd_Top10`) ou prendre l'exact contre-pied des 5 pires bots (`Fade_Bottom5`). |
| **7. Témoins (`_Temoin`)** | 3 | Groupe de contrôle scientifique : `Singe_Aleatoire` (bruit pur), `Le_Permabull` (100 % Long) et `Le_Permabear` (100 % Short). |

---

## Moteur Financier & Modélisation du Risque

* **Position Sizing par Demi-Critère de Kelly :**  
  Pour les agents adaptatifs, le capital engagé est modulé en fonction du winrate réel $p$ et du ratio Risk/Reward $b = 1,8$ :
  $$f^* = \frac{1}{2} \left( p - \frac{1 - p}{b} \right)$$
  Borné entre 12 % et 35 % du capital pour éviter le risque de ruine.
* **Capital Virtuel Négatif Protégé :**  
  Les bots perdants peuvent continuer de plonger dans le négatif comptable sans bloquer le moteur, afin d'alimenter en continu les stratégies contrariennes (`Fade_Bottom5`). Leur assiette de calcul de marge est planchée à $100\,\$$ pour préserver l'intégrité des formules.
* **Prise en Compte des Coûts Réels :**  
  Intégration systématique des frais Maker (`0,02 %`), du slippage/spread (`0,08 %`) et du *funding rate* journalier (`0,06 %`) décompté au prorata temporis.

---

## Commandes Discord V8.5

* `!sniper` : Terminal d'analyse temps réel avec sélection par boutons (Prix, ATR %, Régime ADX, Consensus des Familles, Score ML, Alertes News).
* `!marches` : État d'ouverture des 6 marchés et statut du **Bouclier Vendredi Soir**.
* `!chasse` : Compte à rebours de l'incubation de 14 jours et cibles actives des Méta-Bots (`Crowd_Top10` et `Fade_Bottom5`).
* `!lb` : Classement général paginé (100 bots + joueur humain) avec PnL %, Winrate et cumul des frais payés.
* `!portfolio` : Focus sur les 10 meilleurs bots actuels de l'écosystème.
* `!ml` : Diagnostic des modèles d'arbres GradientBoosting par actif (Accuracy Train/Val, balance des classes, top features).
* `!rl` : Inspection des coefficients et seuils d'entrée appris par les 15 agents auto-adaptatifs.
* `!allpos` : Liste détaillée des positions actives (avec mention du statut TP1 atteint).
* `!buy <actif>` / `!sell <actif>` / `!mypos` : Interface de trading manuel permettant à l'utilisateur de concourir dans les mêmes conditions d'exécution.

---

## Disclaimer 

Ce logiciel est un laboratoire de recherche en finance quantitative, data science et modélisation multi-agents à vocation strictement expérimentale et éducative (Paper Trading). Les signaux et statistiques générés ne constituent en aucun cas des conseils financiers ou des incitations à l'investissement sur des fonds réels.
Merci de me demander pour toute reproduction, contribution ou utilisation. 
Usage à des fins commerciales interdit. 


~ Rémy Mahé

