#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prediction Models - Factor-based return prediction utilities

Hand                if weighted_predictions.std() > 1e-8:  # Avoid division by zero
                    # Use mean ratio scaling: mean(actual) / mean(predicted)
                    mean_actual = y.mean()
                    mean_predicted = weighted_predictions.mean()
                    
                    if abs(mean_predicted) > 1e-8:  # Avoid division by zero
                        scaling_factor = mean_actual / mean_predicted
                        print(f"✅ Using mean ratio scaling: {scaling_factor:.6f}")
                    else:
                        scaling_factor = 1.0
                        print("⚠️ Mean predicted is zero, using default scaling: 1.0")vel prediction using linear models and IC-weighted approaches.
"""

import pandas as pd
import numpy as np
from typing import Dict, List
import warnings
warnings.filterwarnings('ignore')


def predict_returns(test_factors: pd.DataFrame, trained_model: Dict, 
                   selected_factors: List[str]) -> pd.Series:
    """
    Apply trained model to predict returns on test data.
    
    Args:
        test_factors: Test period factor data
        trained_model: Previously trained model with coefficients
        selected_factors: List of selected factor names
        
    Returns:
        Series of predicted returns for test period
    """
    try:
        print(f"🔮 Predicting returns using {len(selected_factors)} factors...")
        
        if 'coefficients' not in trained_model:
            print("⚠️ No model coefficients in trained model")
            return pd.Series()
        
        # Apply trained model to test data (integrated logic)
        coefficients = trained_model['coefficients']
        
        # Ensure selected factors are available in test data
        available_factors = [f for f in selected_factors if f in test_factors.columns]
        if not available_factors:
            print("⚠️ No selected factors available in test data")
            return pd.Series()
        
        missing_factors = set(selected_factors) - set(available_factors)
        if missing_factors:
            print(f"⚠️ Missing factors in test data: {list(missing_factors)[:3]}...")
        
        # Apply coefficients to test factors
        test_factor_subset = test_factors[available_factors]
        
        # Scale test factors if scaler is available (for IC-weighted models)
        if 'scaler' in trained_model and trained_model['scaler'] is not None:
            test_factor_scaled = pd.DataFrame(
                trained_model['scaler'].transform(test_factor_subset),
                index=test_factor_subset.index,
                columns=test_factor_subset.columns
            )
            coeff_subset = coefficients.reindex(available_factors, fill_value=0)
            
            # Calculate predictions: Σ(scaled_factor_level * coefficient)
            predictions = (test_factor_scaled * coeff_subset).sum(axis=1)
        else:
            # Fallback for non-scaled models
            coeff_subset = coefficients.reindex(available_factors, fill_value=0)
            predictions = (test_factor_subset * coeff_subset).sum(axis=1)
        
        # Apply scaling factor if available
        if 'scaling_factor' in trained_model and trained_model['scaling_factor'] is not None:
            predictions *= trained_model['scaling_factor']
        
        r2_score = trained_model.get('test_r2', 'N/A')
        print(f"✅ Generated {len(predictions)} predictions using {len(available_factors)} factors" + 
              (f" (R²: {r2_score:.4f})" if isinstance(r2_score, (int, float)) else ""))
        
        return predictions
        
    except Exception as e:
        print(f"❌ Return prediction failed: {e}")
        return pd.Series()


def train_model(factors: pd.DataFrame, returns: pd.Series,
               selected_factors: List[str], model_type: str = 'ic_weighted',
               ic_weighting_method: str = 'ic_signed',
               scale_ic_predictions: bool = True,
               pre_calculated_metrics: pd.DataFrame = None) -> Dict:
    """
    Train prediction model using integrated logic.
    
    Args:
        factors: Factor level data 
        returns: Return series to predict
        selected_factors: List of factor names to use
        model_type: 'linear', 'ridge', 'lasso', 'elastic_net', 'ic_weighted'
        ic_weighting_method: 'ic_abs', 'ic_signed', 'ir_abs', 'ir_signed'
        scale_ic_predictions: Whether to apply linear scaling to IC predictions
        pre_calculated_metrics: Pre-calculated IC/IR metrics to avoid recalculation
        
    Returns:
        Dictionary with prediction results and model coefficients
    """
    try:
        # Select available factors
        available_factors = [f for f in selected_factors if f in factors.columns]
        if not available_factors:
            return {'error': 'No selected factors found in data'}
        
        factor_data = factors[available_factors].copy()
        
        # Prepare prediction data: factor levels at t predict returns at t+1
        future_returns = returns.shift(-1).dropna()
        
        # Align data
        common_dates = factor_data.index.intersection(future_returns.index)
        if len(common_dates) < 20:
            return {'error': 'Insufficient common data points'}
        
        X = factor_data.loc[common_dates].fillna(method='ffill').fillna(0)
        y = future_returns.loc[common_dates]
        
        # Use IC-weighted approach (default for our system)
        if model_type == 'ic_weighted':
            # Scale factors to ensure fair weighting (important for IC calculations)
            from sklearn.preprocessing import StandardScaler
            scaler = StandardScaler()
            X_scaled = pd.DataFrame(
                scaler.fit_transform(X),
                index=X.index,
                columns=X.columns
            )
            
            # Calculate IC weights on scaled factors
            ic_weights = _calculate_ic_weights(X_scaled, y, ic_weighting_method, pre_calculated_metrics)
            
            # Calculate weighted predictions using scaled factors
            weighted_predictions = (X_scaled * ic_weights).sum(axis=1)
            mean_actual = abs(y).mean()
            mean_predicted = abs(weighted_predictions).mean()
            
            if abs(mean_predicted) > 1e-8:
                scaling_factor = mean_actual / mean_predicted
                print(f"✅ Using mean ratio scaling: {scaling_factor:.6f}")
            else:
                scaling_factor = 1.0
                print("⚠️ Mean predicted is zero, using default scaling: 1.0")
            
            return {
                'coefficients': ic_weights,
                'scaling_factor': scaling_factor,
                'scaler': scaler,  # Include scaler for test data
                'test_r2': -1,  # Not applicable for IC method
                'model_type': model_type,
                'feature_names': available_factors
            }
        
        # Regression-based approaches
        else:
            from sklearn.linear_model import LinearRegression, Ridge, Lasso, ElasticNet
            from sklearn.preprocessing import StandardScaler
            from sklearn.metrics import r2_score
            
            # Split into train/test (70/30)
            split_idx = int(len(X) * 0.7)
            X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
            y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
            
            # Normalize factors
            scaler = StandardScaler()
            X_train_scaled = pd.DataFrame(
                scaler.fit_transform(X_train),
                index=X_train.index,
                columns=X_train.columns
            )
            X_test_scaled = pd.DataFrame(
                scaler.transform(X_test),
                index=X_test.index,
                columns=X_test.columns
            )
            
            # Initialize model
            if model_type == 'linear':
                model = LinearRegression()
            elif model_type == 'ridge':
                model = Ridge(alpha=1.0)
            elif model_type == 'lasso':
                model = Lasso(alpha=0.1)
            elif model_type == 'elastic_net':
                model = ElasticNet(alpha=0.1, l1_ratio=0.5)
            else:
                return {'error': f'Unknown model type: {model_type}'}
            
            # Train model
            model.fit(X_train_scaled, y_train)
            
            # Make predictions
            y_test_pred = model.predict(X_test_scaled)
            test_r2 = r2_score(y_test, y_test_pred)
            
            # Extract coefficients
            coefficients = pd.Series(model.coef_, index=available_factors)
            
            return {
                'coefficients': coefficients,
                'test_r2': test_r2,
                'model_type': model_type,
                'feature_names': available_factors,
                'scaler': scaler
            }
            
    except Exception as e:
        return {'error': f'Model training failed: {e}'}


def _calculate_ic_weights(factors: pd.DataFrame, returns: pd.Series, 
                         method: str = 'ic_signed',
                         pre_calculated_metrics: pd.DataFrame = None) -> pd.Series:
    """Calculate IC-based weights for factors using pre-calculated metrics when available."""
    weights = pd.Series(index=factors.columns, dtype=float)
    
    # Use pre-calculated metrics if available
    if pre_calculated_metrics is not None and not pre_calculated_metrics.empty:
        print(f"✅ Using pre-calculated metrics for {len(factors.columns)} factors")
        
        for factor in factors.columns:
            if factor in pre_calculated_metrics.index:
                if method == 'ic_signed':
                    weights[factor] = pre_calculated_metrics.loc[factor, 'IC']
                elif method == 'ic_abs':
                    weights[factor] = pre_calculated_metrics.loc[factor, 'IC_abs']
                elif method == 'ir_signed':
                    weights[factor] = pre_calculated_metrics.loc[factor, 'IR']
                elif method == 'ir_abs':
                    weights[factor] = abs(pre_calculated_metrics.loc[factor, 'IR'])
                else:
                    weights[factor] = pre_calculated_metrics.loc[factor, 'IC']
            else:
                print(f"⚠️ Factor {factor} not found in pre-calculated metrics, using fallback")
                weights[factor] = factors[factor].corr(returns)
    else:
        # Fallback to original calculation if no pre-calculated metrics
        print(f"⚠️ No pre-calculated metrics available, calculating IC for {len(factors.columns)} factors")
        for factor in factors.columns:
            if method == 'ic_signed':
                weights[factor] = factors[factor].corr(returns)
            elif method == 'ic_abs':
                weights[factor] = abs(factors[factor].corr(returns))
            elif method == 'ir_signed':
                ic = factors[factor].corr(returns)
                ic_std = ic  # Simplified IR calculation
                weights[factor] = ic / max(ic_std, 0.001) if ic_std != 0 else 0
            elif method == 'ir_abs':
                ic = factors[factor].corr(returns)
                ic_std = abs(ic)  # Simplified IR calculation
                weights[factor] = abs(ic) / max(ic_std, 0.001) if ic_std != 0 else 0
            else:
                weights[factor] = factors[factor].corr(returns)
    
    return weights.fillna(0)


def _predict_with_ic_weights(X_train: pd.DataFrame, X_test: pd.DataFrame,
                           y_train: pd.Series, y_test: pd.Series,
                           factor_names: List[str], weighting_method: str,
                           normalize_factors: bool, prediction_lag: int,
                           scale_predictions: bool = True) -> Dict:
    """
    Helper function for IC-weighted factor prediction with linear scaling
    
    Args:
        X_train, X_test: Training and test factor data
        y_train, y_test: Training and test returns
        factor_names: List of factor names
        weighting_method: IC weighting method
        normalize_factors: Whether factors are normalized
        prediction_lag: Prediction horizon
        scale_predictions: Whether to apply linear scaling to match return magnitude
        
    Returns:
        Prediction results with IC weights and optional linear scaling
    """
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import mean_squared_error, r2_score
    from ..analysis.metrics import calculate_metrics
    
    try:
        # Normalize factors if requested
        scaler = None
        if normalize_factors:
            scaler = StandardScaler()
            X_train_scaled = pd.DataFrame(
                scaler.fit_transform(X_train),
                index=X_train.index,
                columns=X_train.columns
            )
            X_test_scaled = pd.DataFrame(
                scaler.transform(X_test),
                index=X_test.index,
                columns=X_test.columns
            )
        else:
            X_train_scaled = X_train
            X_test_scaled = X_test
        
        # Calculate IC metrics on training data
        train_metrics = calculate_metrics(X_train_scaled, y_train)
        
        if train_metrics.empty:
            return {'error': 'Could not calculate IC metrics on training data'}
        
        # Calculate IC weights based on training data
        if weighting_method == 'ic_abs':
            ic_values = train_metrics['IC_abs'].reindex(factor_names).fillna(0)
        elif weighting_method == 'ic_signed':
            ic_values = train_metrics['IC'].reindex(factor_names).fillna(0)
        elif weighting_method == 'ir_abs':
            ic_values = train_metrics['IR'].abs().reindex(factor_names).fillna(0)
        elif weighting_method == 'ir_signed':
            ic_values = train_metrics['IR'].reindex(factor_names).fillna(0)
        else:
            ic_values = train_metrics['IC_abs'].reindex(factor_names).fillna(0)
        
        # Normalize weights to sum to 1
        if ic_values.sum() == 0:
            weights = pd.Series(1.0 / len(factor_names), index=factor_names)
        else:
            if weighting_method in ['ic_abs', 'ir_abs']:
                weights = ic_values / ic_values.sum()
            else:
                # For signed IC/IR, we need to handle positive and negative weights
                weights = ic_values / ic_values.abs().sum()
        
        # Create weighted portfolio predictions
        train_weighted = (X_train_scaled * weights).sum(axis=1)
        test_weighted = (X_test_scaled * weights).sum(axis=1)
        
        # For IC-weighted approach, the "prediction" is the weighted factor score
        # Apply linear scaling if requested
        train_pred = train_weighted
        test_pred = test_weighted
        
        # Apply linear scaling if requested
        scaling_factor = 1.0
        if scale_predictions and len(y_train) > 1:
            # Optimal linear scaling: minimize MSE with scaling factor
            from sklearn.linear_model import LinearRegression
            scale_model = LinearRegression(fit_intercept=False)
            scale_model.fit(train_pred.values.reshape(-1, 1), y_train.values)
            scaling_factor = scale_model.coef_[0]
            
            # Apply scaling
            train_pred = train_pred * scaling_factor
            test_pred = test_pred * scaling_factor
        
        # Calculate metrics
        train_r2 = r2_score(y_train, train_pred) if len(y_train) > 1 else 0
        test_r2 = r2_score(y_test, test_pred) if len(y_test) > 1 else 0
        train_mse = mean_squared_error(y_train, train_pred)
        test_mse = mean_squared_error(y_test, test_pred)
        
        # Direction accuracy
        train_direction = np.mean(np.sign(train_pred) == np.sign(y_train)) if len(y_train) > 0 else 0
        test_direction = np.mean(np.sign(test_pred) == np.sign(y_test)) if len(y_test) > 0 else 0
        
        # Prediction series
        predictions = pd.Series(test_pred.values, index=X_test.index, name='ic_weighted_predictions')
        
        return {
            'model': None,  # No sklearn model for IC weighting
            'scaler': scaler,
            'coefficients': weights,  # IC weights instead of regression coefficients
            'ic_metrics': train_metrics.loc[factor_names] if not train_metrics.empty else pd.DataFrame(),
            'weighting_method': weighting_method,
            'scaling_method': 'linear' if scale_predictions else 'none',
            'scaling_factor': scaling_factor,
            'intercept': 0,  # No intercept in IC weighting
            'predictions': predictions,
            'actual_returns': y_test,
            'train_r2': train_r2,
            'test_r2': test_r2,
            'train_mse': train_mse,
            'test_mse': test_mse,
            'train_direction': train_direction,
            'test_direction': test_direction,
            'feature_names': factor_names,
            'prediction_lag': prediction_lag,
            'model_type': 'ic_weighted'
        }
        
    except Exception as e:
        return {'error': f'IC-weighted prediction failed: {str(e)}'}


def interpret_linear_model_coefficients(trained_model: Dict, 
                                       top_n: int = 10) -> pd.DataFrame:
    """
    Interpret linear model coefficients or IC weights for factor-level prediction
    
    Args:
        trained_model: Results from _train_prediction_model
        top_n: Number of top factors to show
        
    Returns:
        DataFrame with coefficient/weight interpretation
    """
    if 'error' in trained_model or 'coefficients' not in trained_model:
        return pd.DataFrame()
    
    coeffs = trained_model['coefficients']
    model_type = trained_model.get('model_type', 'unknown')
    
    if coeffs.empty:
        return pd.DataFrame()
    
    # Create interpretation DataFrame
    if model_type == 'ic_weighted':
        # For IC weights, interpretation is different
        interpretation = pd.DataFrame({
            'factor': coeffs.index,
            'weight': coeffs.values,
            'abs_weight': np.abs(coeffs.values),
            'interpretation': [
                f"Factor gets {w:.1%} weight ({'positive' if w > 0 else 'negative'} contribution)"
                for w in coeffs.values
            ],
            'weight_type': 'IC Weight'
        })
        
        # Add IC metrics if available
        if 'ic_metrics' in trained_model and not trained_model['ic_metrics'].empty:
            ic_metrics = trained_model['ic_metrics']
            interpretation = interpretation.merge(
                ic_metrics[['IC', 'IC_abs', 'IR']].round(4),
                left_on='factor', right_index=True, how='left'
            )
    else:
        # For regression coefficients
        interpretation = pd.DataFrame({
            'factor': coeffs.index,
            'coefficient': coeffs.values,
            'abs_coefficient': np.abs(coeffs.values),
            'interpretation': [
                f"{'Higher' if c > 0 else 'Lower'} {factor} → {'Higher' if c > 0 else 'Lower'} returns"
                for factor, c in coeffs.items()
            ],
            'sensitivity': [
                f"1 unit ↑ in {factor} → {c:.4f} ↑ in returns"
                for factor, c in coeffs.items()
            ],
            'weight_type': 'Regression Coefficient'
        })
    
    # Sort by absolute value
    sort_col = 'abs_weight' if model_type == 'ic_weighted' else 'abs_coefficient'
    interpretation = interpretation.sort_values(sort_col, ascending=False)
    
    # Add ranking
    interpretation['rank'] = range(1, len(interpretation) + 1)
    
    return interpretation.head(top_n) if top_n is not None else interpretation
