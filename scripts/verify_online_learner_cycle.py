import sys
import logging
from datetime import datetime

sys.path.insert(0, ".")

from backend.models.database import Base, engine, SessionLocal, Trade
from backend.models.outcome_tables import Base as OutcomeBase, StrategyOutcome
from backend.core.online_learner import OnlineLearner

logging.basicConfig(level=logging.INFO)
from loguru import logger

def run_verification():
    logger.info("Initializing database schemas...")
    Base.metadata.drop_all(bind=engine)
    OutcomeBase.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    OutcomeBase.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    # Create some dummy trades to test the learner
    strategies = ["btc_momentum", "weather_emos", "copy_trader"]
    dummy_trades = []
    
    for i, strat in enumerate(strategies):
        for j in range(3):  # 3 trades per strategy
            trade = Trade(
                strategy=strat,
                trading_mode="testnet",
                market_ticker=f"TEST_MARKET_{i}_{j}",
                result="win" if j < 2 else "loss",
                pnl=10.0 if j < 2 else -5.0,
                model_probability=0.7,
                confidence=0.8,
                settled=True,
                settlement_time=datetime.utcnow()
            )
            db.add(trade)
            dummy_trades.append(trade)
            
    db.commit()
    logger.info(f"Inserted {len(dummy_trades)} test trades.")
    
    learner = OnlineLearner()
    for trade in dummy_trades:
        learner.on_trade_settled(trade, db)
        
    logger.info("Executed learner.on_trade_settled for all dummy trades.")
    
    outcomes = db.query(StrategyOutcome).all()
    logger.info(f"Verified {len(outcomes)} StrategyOutcomes in repository.")
    assert len(outcomes) == len(dummy_trades)
    
    allocations = learner.get_allocation(strategies, total_capital=1000.0)
    logger.info(f"Thompson Sampler allocations: {allocations}")
    
    print("\n✅ OnlineLearner Cycle Verification Completed Successfully!")

if __name__ == "__main__":
    run_verification()
