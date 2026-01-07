"""
Optimized Bond Option Pricing Demo

@author: CMBC
Simplified main interface with better error handling and user experience
"""
import os
import sys
from typing import Optional, Dict, Any

import numpy as np
import pathlib

# Ensure project root is on sys.path so absolute imports (e.g., `curves`, `settings`) work
THIS_FILE = pathlib.Path(__file__).resolve()
PROJECT_ROOT = str(THIS_FILE.parents[2])  # .../bin-v2.9
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Also include the `derivatives` package directory for safety (not strictly needed once root is added)
# DERIVATIVES_DIR = str(THIS_FILE.parents[1])
# if DERIVATIVES_DIR not in sys.path:
#     sys.path.insert(0, DERIVATIVES_DIR)

from derivatives.pricer import BondOption, InterestRateOption
from curves.utils.file import updatePKL
from curves.utils.loader import loadInstrumentDefinition


class OptionPricingDemo:
    """Encapsulated demo class for better organization"""
    
    def __init__(self):
        self.bond_env = None
        self.default_bond = None
        self._load_environment()

    def _load_environment(self):
        """Load bond environment once"""
        try:
            print("Loading bond environment...")
            self.bond_env = loadInstrumentDefinition("TBond")
            self.default_bond = self.bond_env['Def'].loc['240011.IB']
            print("✅ Environment loaded successfully")
        except Exception as e:
            print(f"❌ Failed to load environment: {e}")
            raise

    def create_bond_option(self, **kwargs) -> BondOption:
        """Create bond option with default parameters"""
        defaults = {
            'underlying': self.default_bond,
            'exercise_date': '20250211',
            'expiry_date': '20250511', 
            'eval_date': '20250211',
            'strike': 105.524,
            'notional': 20_000_000,
            'option_type': 'call'
        }
        defaults.update(kwargs)
        print('DEBUG create_bond_option kwargs:', defaults)
        return BondOption(**defaults)

    def create_interest_rate_option(self, **kwargs) -> InterestRateOption:
        """Create interest rate option with default parameters"""
        defaults = {
            'underlying': self.default_bond,
            'exercise_date': '20250211',
            'expiry_date': '20250511',
            'eval_date': '20250211', 
            'strike_yield': 1.6265,  # 1.6265%
            'notional': 20_000_000,
            'option_type': 'call'
        }
        defaults.update(kwargs)
        return InterestRateOption(**defaults)

    def display_results(self, option_type: str, results: Dict[str, Any]):
        """Display results in a formatted way"""
        print(f"\n{'='*50}")
        print(f" {option_type.upper()} OPTION RESULTS")
        print(f"{'='*50}")
        
        # Common fields
        print(f"Notional:        {results['notional']:>15,.0f}")
        print(f"Option Type:     {results['option_type']:>15s}")
        print(f"Market Value:    {results['price']:>15,.2f}")
        print(f"Price per 100:   {100*results['price']/results['notional']:>15,.4f}")
        
        # Show both strike price and yield, and current price and yield
        strike = results.get('strike', float('nan'))
        strike_yield = results.get('strike_yield', None)
        underlying_price = results.get('underlying_price', float('nan'))
        underlying_ytm = results.get('underlying_ytm', None)
        duration = results.get('duration', float('nan'))
        bond = results.get('underlying', getattr(self, 'default_bond', None))
        eval_date = results.get('eval_date', None)

        # Compute missing strike_yield from strike and bond if possible
        # if (strike_yield is None or not np.isfinite(strike_yield)) and bond is not None and np.isfinite(strike):
        #     try:
        #         from pricer import BondPricer
        #         pricer = BondPricer(bond)
        #         # Use a root-finding method to get YTM from price
        #         def price_to_ytm(price):
        #             # Use bond pricer to get price for a given ytm
        #             _, clean, _, _ = pricer.compute_metrics(eval_date)
        #             return clean - price
        #         # For simplicity, use the bond's current ytm as approximation
        #         strike_yield = pricer.get_ytm(eval_date)
        #     except Exception as e:
        #         strike_yield = float('nan')

        # # Compute missing underlying_ytm from underlying_price and bond if possible
        # if (underlying_ytm is None or not np.isfinite(underlying_ytm)) and bond is not None and np.isfinite(underlying_price):
        #     try:
        #         from pricer import BondPricer
        #         pricer = BondPricer(bond)
        #         underlying_ytm = pricer.get_ytm(eval_date)
        #     except Exception as e:
        #         underlying_ytm = float('nan')

        strike_yield_disp = f"{strike_yield*100:14.4f}%" if strike_yield is not None else "     (n/a)"
        underlying_ytm_disp = f"{underlying_ytm*100:14.4f}%" if underlying_ytm is not None else "     (n/a)"
        # Format values, replacing NaN with (n/a)
        def format_value(val, format_str, fallback="(n/a)"):
            if val is None or np.isnan(val):
                return f"{fallback:>15s}"
            return format_str.format(val)
        
        print(f"Strike Price:    {format_value(strike, '{:>15.4f}')}")
        print(f"Strike Yield:    {strike_yield_disp}")
        print(f"Current Price:   {format_value(underlying_price, '{:>15.4f}')}")
        print(f"Current Yield:   {underlying_ytm_disp}")
        print(f"Duration:        {format_value(duration, '{:>15.4f}')}")
        
        # Greeks
        print(f"\nGREEKS:")
        delta = results.get('delta', float('nan'))
        delta_yield = results.get('delta_yield', float('nan'))
        gamma = results.get('gamma', float('nan'))
        vega = results.get('vega', float('nan'))
        theta = results.get('theta', float('nan'))
        rho = results.get('rho', float('nan'))
        
        print(f"Delta (w.r.t. Price): {format_value(delta, '{:>10,.4f}')}")
        print(f"Delta (w.r.t. Yield): {format_value(delta_yield, '{:>10,.4f}')}")
        print(f"Gamma:           {format_value(gamma, '{:>15,.2f}')}")
        print(f"Vega:            {format_value(vega, '{:>15,.2f}')}")
        print(f"Theta:           {format_value(theta, '{:>15,.2f}')}")
        print(f"Rho:             {format_value(rho, '{:>15,.2f}')}")
        
        # Market data
        print(f"\nMARKET DATA:")
        time_to_expiry = results.get('time_to_expiry', float('nan'))
        volatility = results.get('volatility', float('nan'))
        risk_free_rate = results.get('risk_free_rate', float('nan'))
        
        print(f"Time to Expiry:  {format_value(time_to_expiry, '{:>14.2f} months')}")
        print(f"Volatility:      {format_value(volatility*100 if not np.isnan(volatility) else volatility, '{:>14.4f}%')}")
        print(f"Risk Free Rate:  {format_value(risk_free_rate*100 if not np.isnan(risk_free_rate) else risk_free_rate, '{:>14.4f}%')}")

    def run_bond_option(self) -> bool:
        """Run bond option pricing"""
        try:
            print(f"\n>>> Running Bond Option Pricing...")
            option = self.create_bond_option()
            results = option.price_option()
            self.display_results('bond', results)
            print(f"\n✅ Bond Option pricing completed successfully!")
            return True
        except Exception as e:
            import traceback
            print(f"\n❌ Bond Option pricing failed: {e}")
            traceback.print_exc()
            return False

    def run_interest_rate_option(self) -> bool:
        """Run interest rate option pricing"""
        try:
            print(f"\n>>> Running Interest Rate Option Pricing...")
            option = self.create_interest_rate_option()
            results = option.price_option()
            self.display_results('interest_rate', results)
            print(f"\n✅ Interest Rate Option pricing completed successfully!")
            return True
        except Exception as e:
            import traceback
            print(f"\n❌ Interest Rate Option pricing failed: {e}")
            traceback.print_exc()
            return False

    def get_user_choice(self) -> str:
        """Get user input with proper error handling"""
        try:
            choice = input("Enter choice (1/2/3) or press Enter for Bond Option [1]: ").strip()
            return choice if choice else '1'
        except (EOFError, KeyboardInterrupt):
            return '1'  # Default choice

    def run_interactive_demo(self):
        """Run the interactive demo"""
        print("="*60)
        print(" BOND OPTION PRICING SYSTEM")
        print("="*60)
        print("Choose option type:")
        print("1. Bond Option (price-based)")
        print("2. Interest Rate Option (YTM-based)")
        print("3. Run both")
        print("-" * 60)
        
        choice = self.get_user_choice()
        print(f"Selected: {choice}")
        
        success = True
        if choice == '2':
            success = self.run_interest_rate_option()
        elif choice == '3':
            success1 = self.run_bond_option()
            print("\n" + "="*60)
            success2 = self.run_interest_rate_option()
            success = success1 and success2
        else:
            success = self.run_bond_option()
        
        if success:
            print(f"\n🎉 Demo completed successfully!")
        else:
            print(f"\n⚠️  Demo completed with errors.")


def main(option_type_choice: str = 'bond', **kwargs):
    """
    Simplified main function for programmatic use
    
    Parameters:
    -----------
    option_type_choice : str
        'bond' or 'interest_rate'
    **kwargs : additional parameters for option creation
    """
    demo = OptionPricingDemo()
    
    if option_type_choice == 'interest_rate':
        option = demo.create_interest_rate_option(**kwargs)
        results = option.price_option()
        demo.display_results('interest_rate', results)
    else:
        option = demo.create_bond_option(**kwargs)
        results = option.price_option()
        demo.display_results('bond', results)
    
    return results


if __name__ == '__main__':
    try:
        demo = OptionPricingDemo()
        demo.run_interactive_demo()
    except KeyboardInterrupt:
        print(f"\n\n👋 Demo interrupted by user. Goodbye!")
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()


        #%%
    import math
    from scipy.stats import norm

    # Given values
    P0 = 105.4477*0.99#105.6038  # Spot price of the bond
    K = 105.5240  # Strike price
    T = 2.92 / 12  # Time to expiry in years
    sigma = 0.0287  # Volatility (annualized)
    r = 0.018507  # Risk-free rate (annualized)
    notional = 20_000_000  # Notional

    # Calculate d1 and d2
    d1 = (math.log(P0 / K) + (0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    # Cumulative normal distribution for d1 and d2
    N_d1 = norm.cdf(d1)
    N_d2 = norm.cdf(d2)

    # Call option price (Black Model)
    C = math.exp(-r * T) * (P0 * N_d1 - K * N_d2)

    # Greeks
    delta = math.exp(-r * T) * N_d1  # Delta
    gamma = math.exp(-r * T) * norm.pdf(d1) / (P0 * sigma * math.sqrt(T))  # Gamma
    vega = P0 * math.sqrt(T) * math.exp(-r * T) * norm.pdf(d1)  # Vega

    # Results
    print("Option Price (C):", C)
    print("Market value:", C * notional/100)
    print("Delta:", delta * notional/100)
    print("Gamma:", gamma * notional/100)
    print("Vega:", vega * notional/100)