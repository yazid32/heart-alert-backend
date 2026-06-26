"""
VISUALISATION DE LA COMPARAISON DES MODÈLES
XGBoost vs 5 Autres Modèles sur 1 190 Patients
"""

import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import pandas as pd

# Style
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

# ====================================================================
# DONNÉES (1 190 Patients)
# ====================================================================
modeles = ['XGBoost', 'random forest', 'LightGBM', 'CatBoost', 'SVM', 'Régression Logistique']
accuracy = [93.70, 91.60, 91.18, 88.66, 87.82, 84.03]
precision = [95.12, 92.06, 91.34, 88.37, 86.47, 84.38]
rappel = [92.86, 92.06, 92.06, 90.48, 91.27, 85.71]
f1 = [93.98, 92.06, 91.70, 89.41, 88.80, 85.04]
auc = [97.17, 97.41, 96.53, 95.76, 93.52, 90.41]

# Matrice de confusion - XGBoost seulement
cm_xgb = [[106, 6], [9, 117]]

# Importances des caractéristiques - XGBoost
caracteristiques = ['slope', 'chest pain type', 'gender', 'exercise angina', 'fasting blood sugar', 
                    'ST depression', 'max heart rate', 'age', 'cholesterol', 'resting BP', 'resting ECG']
importances = [42.3, 16.3, 8.9, 7.0, 5.1, 4.8, 3.5, 3.2, 2.8, 2.1, 1.6]



# ====================================================================
# GRAPHIQUE 4 : COMPARAISON COMPLÈTE - TOUS LES MODÈLES
# ====================================================================
fig, ax = plt.subplots(figsize=(14, 8))

x = np.arange(len(modeles))
largeur = 0.15

metriques_noms = ['Exactitude', 'Précision', 'Rappel', 'F1-Score', 'AUC-ROC']
couleurs_metriques = ['#2ecc71', '#3498db', '#f39c12', '#e74c3c', '#9b59b6']
valeurs = [accuracy, precision, rappel, f1, auc]

for i, (nom, couleur, vals) in enumerate(zip(metriques_noms, couleurs_metriques, valeurs)):
    decalage = (i - 2) * largeur
    bars = ax.bar(x + decalage, vals, largeur, label=nom, color=couleur, edgecolor='black', linewidth=0.8)
    
    for j, bar in enumerate(bars):
        hauteur = bar.get_height()
        if j == 0:
            ax.text(bar.get_x() + bar.get_width()/2., hauteur + 0.5,
                    f'{hauteur:.1f}%', ha='center', va='bottom', fontsize=8, fontweight='bold', rotation=90)
        elif hauteur > 85:
            ax.text(bar.get_x() + bar.get_width()/2., hauteur + 0.5,
                    f'{hauteur:.1f}%', ha='center', va='bottom', fontsize=7, rotation=90)

ax.set_xlabel('Modèles', fontsize=14, fontweight='bold')
ax.set_ylabel('Score (%)', fontsize=14, fontweight='bold')
ax.set_title('Comparaison des Performances - Tous les Modèles (1 190 patients)', fontsize=16, fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels(modeles, fontsize=11)
ax.legend(loc='upper left', fontsize=11)
ax.set_ylim(80, 100)
ax.axhline(y=93.70, color='#2ecc71', linestyle='--', alpha=0.5, linewidth=1.5)
ax.text(5.5, 93.70 + 0.5, 'XGBoost : 93,70%', fontsize=10, color='#2ecc71', fontweight='bold')

plt.tight_layout()
plt.savefig('comparaison_complete.png', dpi=300, bbox_inches='tight')
print("✅ Sauvegardé : comparaison_complete.png")
