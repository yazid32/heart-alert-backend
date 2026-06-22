"""
Heart Disease Prediction Model Loader
Loads the trained Random Forest model and makes predictions
"""

import joblib
import numpy as np
import os
import xgboost as xgb
MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', '..',
 '"C:\Users\Kader\Documents\heart-disease-project\etat-de-lart\models\xgboost\xgboost_model.pkl"')

try:
    model = joblib.load(MODEL_PATH)
    print(f"✅ Model loaded successfully")
except Exception as e:
    print(f"❌ Error loading model: {e}")
    model = None

def predict_heart_disease(age, sex, cp, trestbps, chol, fbs, restecg, thalach, exang, oldpeak, slope):
    if model is None:
        return {
            "error": "Model not loaded",
            "risk_score": 0.5,
            "risk_category": "moderate",
            "has_disease": False,
            "recommendation": "Model unavailable. Please try again later."
        }
    
    features = np.array([[
        age, sex, cp, trestbps, chol, fbs, restecg, 
        thalach, exang, oldpeak, slope
    ]])
    
    prediction = model.predict(features)[0]
    probability = model.predict_proba(features)[0][1]
    
    risk_score = float(probability)
    
    if risk_score < 0.3:
        category = "low"
        recommendation = "Low risk profile. Continue healthy lifestyle and routine screenings."
    elif risk_score < 0.6:
        category = "moderate"
        recommendation = "Monitor closely. Consider lifestyle modifications and regular check-ups."
    else:
        category = "high"
        recommendation = "Immediate cardiology consultation recommended. Further diagnostic tests may be necessary."
    
    return {
        "risk_score": round(risk_score, 2),
        "risk_category": category,
        "has_disease": bool(prediction),
        "recommendation": recommendation
    }