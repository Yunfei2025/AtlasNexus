#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick Configuration Updater for Strategy Improvements

Run this script to quickly apply recommended configurations for:
- Conservative (high win rate, low drawdown)
- Balanced (moderate returns, moderate risk)
- Aggressive (high returns, higher risk)
"""

from factors.config import config_manager
#%%

def apply_conservative_config():
    """
    Conservative configuration: Focus on high win rate and low drawdown.
    Best for risk-averse traders or when starting out.
    
    Expected: Win rate 55-65%, Max DD 8-12%, Sharpe 1.2-1.8
    """
    config = config_manager.model_config
    
    print("🛡️ Applying CONSERVATIVE configuration...")
    
    # Strict factor selection
    config.ic_threshold = 0.12
    config.ir_threshold = 0.8
    config.top_n = 3
    config.lookback_window = 12
    config.use_factor_diversification = True
    config.max_factor_correlation = 0.5
    
    # Simple portfolio for clarity
    config.portfolio_method = 'simple'
    config.max_position = 0.5
    
    # Strong risk management
    config.use_risk_management = True
    config.stop_loss_pct = 0.03
    config.max_drawdown_limit = 0.10
    config.use_volatility_scaling = True
    config.use_drawdown_protection = True
    config.min_position_threshold = 0.15
    config.use_confidence_filtering = True
    
    # Conservative costs
    config.friction_cost = 0.001
    
    print("✅ Conservative config applied!")
    print("   → High win rate focus")
    print("   → Low drawdown target: <10%")
    print("   → Max position: 50%")
    return config


def apply_balanced_config():
    """
    Balanced configuration: Good returns with moderate risk.
    Best for regular trading with established systems.
    
    Expected: Win rate 50-60%, Max DD 12-15%, Sharpe 1.5-2.0
    """
    config = config_manager.model_config
    
    print("⚖️ Applying BALANCED configuration...")
    
    # Moderate factor selection
    config.ic_threshold = 0.08
    config.ir_threshold = 0.7
    config.top_n = 5
    config.lookback_window = 9
    config.use_factor_diversification = True
    config.max_factor_correlation = 0.6
    
    # Intensity portfolio for better sizing
    config.portfolio_method = 'intensity'
    config.max_position = 0.8
    config.tanh_scale = 1.5
    
    # Balanced risk management
    config.use_risk_management = True
    config.stop_loss_pct = 0.05
    config.max_drawdown_limit = 0.15
    config.use_volatility_scaling = True
    config.use_drawdown_protection = True
    config.min_position_threshold = 0.10
    
    # Kelly sizing for optimization
    config.use_kelly_sizing = True
    config.kelly_fraction = 0.25
    
    # Moderate costs
    config.friction_cost = 0.0005
    
    print("✅ Balanced config applied!")
    print("   → Good returns with moderate risk")
    print("   → Target drawdown: 12-15%")
    print("   → Kelly criterion enabled")
    return config


def apply_aggressive_config():
    """
    Aggressive configuration: Higher returns, can handle more risk.
    Best for experienced traders comfortable with volatility.
    
    Expected: Win rate 45-55%, Max DD 15-20%, Sharpe 1.0-1.5
    """
    config = config_manager.model_config
    
    print("🚀 Applying AGGRESSIVE configuration...")
    
    # Looser factor selection (more factors)
    config.ic_threshold = 0.06
    config.ir_threshold = 0.6
    config.top_n = 8
    config.lookback_window = 6
    config.use_factor_diversification = True
    config.max_factor_correlation = 0.7
    
    # Intensity portfolio with aggressive scaling
    config.portfolio_method = 'intensity'
    config.max_position = 1.0
    config.tanh_scale = 2.0
    
    # Looser risk management
    config.use_risk_management = True
    config.stop_loss_pct = 0.08
    config.max_drawdown_limit = 0.20
    config.use_volatility_scaling = True
    config.use_drawdown_protection = False  # Disabled for more aggressive
    config.min_position_threshold = 0.05
    
    # Lower costs (more trading)
    config.friction_cost = 0.0003
    
    print("✅ Aggressive config applied!")
    print("   → Higher returns target")
    print("   → Accepts drawdown: 15-20%")
    print("   → More active trading")
    return config


def apply_win_rate_optimizer():
    """
    Win Rate Optimizer: Maximize win rate at expense of total return.
    Best when you need consistent wins for psychological comfort.
    
    Expected: Win rate 60-70%, Max DD 8-10%, Sharpe 1.0-1.3 (lower returns)
    """
    config = config_manager.model_config
    
    print("🎯 Applying WIN RATE OPTIMIZER configuration...")
    
    # Very strict factor selection
    config.ic_threshold = 0.15
    config.ir_threshold = 1.0
    config.top_n = 2  # Only top 2 factors
    config.lookback_window = 18
    config.use_factor_diversification = True
    config.max_factor_correlation = 0.4
    
    # Simple binary signals
    config.portfolio_method = 'simple'
    config.max_position = 0.3  # Very conservative
    
    # Strict filtering
    config.use_risk_management = True
    config.stop_loss_pct = 0.02
    config.max_drawdown_limit = 0.08
    config.min_position_threshold = 0.20  # Only strong signals
    config.use_confidence_filtering = True
    
    print("✅ Win rate optimizer applied!")
    print("   → Target win rate: >60%")
    print("   → Very selective trading")
    print("   → Lower total returns expected")
    return config


def print_current_config():
    """Display current configuration settings."""
    config = config_manager.model_config
    
    print("\n" + "="*60)
    print("CURRENT CONFIGURATION")
    print("="*60)
    print(f"Factor Selection:")
    print(f"  IC Threshold: {config.ic_threshold:.3f}")
    print(f"  IR Threshold: {config.ir_threshold:.2f}")
    print(f"  Top N Factors: {config.top_n}")
    print(f"  Lookback Window: {config.lookback_window} months")
    print(f"\nPortfolio:")
    print(f"  Method: {config.portfolio_method}")
    print(f"  Max Position: {config.max_position:.1%}")
    print(f"\nRisk Management:")
    print(f"  Enabled: {config.use_risk_management}")
    print(f"  Stop Loss: {config.stop_loss_pct:.1%}")
    print(f"  Max Drawdown Limit: {config.max_drawdown_limit:.1%}")
    print(f"  Volatility Scaling: {config.use_volatility_scaling}")
    print("="*60 + "\n")


def interactive_menu():
    """Interactive menu for selecting configuration."""
    print("\n" + "="*60)
    print("STRATEGY IMPROVEMENT CONFIGURATION TOOL")
    print("="*60)
    print("\nSelect a configuration profile:")
    print("1. Conservative  - High win rate, low drawdown")
    print("2. Balanced      - Moderate returns, moderate risk")
    print("3. Aggressive    - Higher returns, higher risk")
    print("4. Win Rate Max  - Maximize win rate only")
    print("5. Show current  - Display current settings")
    print("0. Exit")
    print("="*60)
    
    while True:
        choice = input("\nEnter choice (0-5): ").strip()
        
        if choice == '1':
            apply_conservative_config()
            print_current_config()
        elif choice == '2':
            apply_balanced_config()
            print_current_config()
        elif choice == '3':
            apply_aggressive_config()
            print_current_config()
        elif choice == '4':
            apply_win_rate_optimizer()
            print_current_config()
        elif choice == '5':
            print_current_config()
        elif choice == '0':
            print("\n👋 Exiting...")
            break
        else:
            print("❌ Invalid choice. Please enter 0-5.")


if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════════════╗
║    STRATEGY IMPROVEMENT CONFIGURATION TOOL                ║
║                                                           ║
║  Quickly apply optimized configurations to improve:       ║
║  • Win Rate                                               ║
║  • Total Returns                                          ║
║  • Maximum Drawdown                                       ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Show current config first
    print_current_config()
    
    # Start interactive menu
    interactive_menu()
