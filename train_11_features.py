"""
============================================
TRAIN 11-FEATURE MODEL FOR APP
Using combined dataset (1,190 rows) - EXCLUDING ca and thal
============================================
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, classification_report
import joblib
import warnings
warnings.filterwarnings('ignore')

print("=" * 70)
print("🏥 TRAINING 11-FEATURE MODEL (excludes ca and thal)")
print("=" * 70)

# ============================================================================
# LOAD LOCAL DATASET
# ============================================================================
print("\n📁 Loading local dataset...")
df = pd.read_csv('clev-dataset.csv')
print(f"   Loaded {len(df)} patient records")
print(f"   Original columns: {df.columns.tolist()}")

# ============================================================================
# RENAME COLUMNS TO STANDARD NAMES
# ============================================================================
print("\n📝 Renaming columns...")
column_mapping = {
    'chest pain type': 'cp',
    'resting bp s': 'trestbps',
    'cholesterol': 'chol',
    'fasting blood sugar': 'fbs',
    'resting ecg': 'restecg',
    'max heart rate': 'thalach',
    'exercise angina': 'exang',
    'ST slope': 'slope'
}
df.rename(columns=column_mapping, inplace=True)
print(f"   Renamed columns: {df.columns.tolist()}")

# ============================================================================
# FIND TARGET COLUMN
# ============================================================================
target_col = 'target' if 'target' in df.columns else df.columns[-1]
print(f"\n🎯 Target column: '{target_col}'")

# ============================================================================
# DEFINE 11 FEATURES (EXCLUDING ca AND thal)
# ============================================================================
features_11 = ['age', 'sex', 'cp', 'trestbps', 'chol', 'fbs', 'restecg',
               'thalach', 'exang', 'oldpeak', 'slope']

# Check which features are available
available_features = [f for f in features_11 if f in df.columns]
missing_features = [f for f in features_11 if f not in df.columns]

if missing_features:
    print(f"\n⚠️ Missing features: {missing_features}")
else:
    print(f"\n✅ All 11 features available: {available_features}")

# ============================================================================
# PREPARE DATA
# ============================================================================
print("\n🔧 Preparing data...")
X = df[available_features].copy()
y = df[target_col].copy()

# Convert target to binary (0 = no disease, 1 = disease)
if y.nunique() > 2:
    y = (y > 0).astype(int)
    print(f"   Converted target to binary (0/1)")

print(f"\n📊 Dataset info:")
print(f"   Total patients: {len(X)}")
print(f"   Features: {X.shape[1]}")
print(f"   Feature names: {X.columns.tolist()}")
print(f"   Healthy (0): {(y == 0).sum()}")
print(f"   Disease (1): {(y == 1).sum()}")
print(f"   Disease prevalence: {(y == 1).mean():.1%}")

# ============================================================================
# SPLIT DATA
# ============================================================================
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

print(f"\n📊 Data split:")
print(f"   Training: {len(X_train)} patients (80%)")
print(f"   Testing: {len(X_test)} patients (20%)")
print(f"   Train - Healthy: {(y_train == 0).sum()}, Disease: {(y_train == 1).sum()}")
print(f"   Test  - Healthy: {(y_test == 0).sum()}, Disease: {(y_test == 1).sum()}")

# ============================================================================
# TRAIN RANDOM FOREST
# ============================================================================
print("\nTraining Random Forest...")
model = RandomForestClassifier(
    n_estimators=100,
    max_depth=10,
    random_state=42,
    n_jobs=-1
)
model.fit(X_train, y_train)
print("  Training complete")

# ============================================================================
# EVALUATE MODEL
# ============================================================================
print("\n📈 Evaluating model on test set...")
y_pred = model.predict(X_test)
y_prob = model.predict_proba(X_test)[:, 1]

accuracy = accuracy_score(y_test, y_pred)
precision = precision_score(y_test, y_pred)
recall = recall_score(y_test, y_pred)
f1 = f1_score(y_test, y_pred)
auc = roc_auc_score(y_test, y_prob)

print(f"\n📊 PERFORMANCE METRICS:")
print(f"   Accuracy:  {accuracy:.4f} ({accuracy:.2%})")
print(f"   Precision: {precision:.4f} ({precision:.2%})")
print(f"   Recall:    {recall:.4f} ({recall:.2%})")
print(f"   F1-Score:  {f1:.4f} ({f1:.2%})")
print(f"   AUC-ROC:   {auc:.4f} ({auc:.2%})")

print(f"\n   Classification Report:")
print(classification_report(y_test, y_pred, target_names=['No Disease', 'Disease']))

# ============================================================================
# CONFUSION MATRIX
# ============================================================================
from sklearn.metrics import confusion_matrix
cm = confusion_matrix(y_test, y_pred)
print(f"\n📊 Confusion Matrix:")
print(f"   ┌─────────────┬─────────────┐")
print(f"   │   TP: {cm[1,1]:3d}    │   FP: {cm[0,1]:3d}    │")
print(f"   ├─────────────┼─────────────┤")
print(f"   │   FN: {cm[1,0]:3d}    │   TN: {cm[0,0]:3d}    │")
print(f"   └─────────────┴─────────────┘")

# ============================================================================
# FEATURE IMPORTANCE
# ============================================================================
print(f"\n🎯 FEATURE IMPORTANCE (Top 11):")
feature_importance = pd.DataFrame({
    'feature': X.columns,
    'importance': model.feature_importances_
}).sort_values('importance', ascending=False)

for idx, row in feature_importance.iterrows():
    bar = "█" * int(row['importance'] * 50)
    print(f"   {row['feature']:12s} : {row['importance']:.4f} ({row['importance']*100:.1f}%) {bar}")

# ============================================================================
# SAVE MODEL
# ============================================================================
print("\n💾 Saving model...")
joblib.dump(model, 'heart_disease_model_11features.pkl')
print("   ✅ Model saved as 'heart_disease_model_11features.pkl'")

# Also save as the main app model (backup)
joblib.dump(model, 'heart_disease_model.pkl')
print("   ✅ Model also saved as 'heart_disease_model.pkl' (for app)")

print("\n" + "=" * 70)
print("✅ TRAINING COMPLETED!")
print("=" * 70)

# ============================================================================
# QUICK TEST
# ============================================================================
print("\n🧪 Quick test on sample patient:")
sample = X_test.iloc[0:1]
pred = model.predict(sample)[0]
prob = model.predict_proba(sample)[0][1]
print(f"   Prediction: {'DISEASE' if pred == 1 else 'HEALTHY'}")
print(f"   Risk score: {prob:.2%}")