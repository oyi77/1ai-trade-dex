import json
from sqlalchemy.orm import sessionmaker
from backend.models.database import Trade, StrategyConfig
from backend.models.database import engine


def backfill_data():
    # Create a new DB session
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Ensure single-threaded locking for SQLite backfills
        with session.begin():
            trades = session.query(Trade).all()
            for trade in trades:
                flags = {}

                # Backfill edge_at_entry
                if trade.edge_at_entry is None:
                    if (
                        trade.model_probability is not None
                        and trade.market_price_at_entry is not None
                    ):
                        trade.edge_at_entry = (
                            trade.model_probability - trade.market_price_at_entry
                        )
                    else:
                        trade.edge_at_entry = 0.0
                        flags["edge_at_entry"] = "set_to_0"

                # Backfill confidence
                if trade.confidence is None:
                    trade.confidence = 0.5
                    flags["confidence"] = "set_to_default"

                # Backfill strategy
                if trade.strategy is None:
                    trade.strategy = "unknown"
                    flags["strategy"] = "set_to_unknown"

                # Handle model_probability == 1.0 case
                if trade.model_probability == 1.0:
                    if (
                        trade.market_price_at_entry is not None
                        and trade.edge_at_entry is not None
                    ):
                        trade.model_probability = (
                            trade.market_price_at_entry + trade.edge_at_entry
                        )
                    else:
                        flags["model_probability"] = "unchanged_due_to_missing_data"

                # Normalize strategy names
                if trade.strategy == "weather":
                    trade.strategy = "weather_emos"
                    flags["strategy"] = "normalized_to_weather_emos"

                # Set data_quality_flags
                if flags:
                    trade.data_quality_flags = json.dumps(flags)

                session.add(trade)

        # Add auto_trader to StrategyConfig if not exists.
        auto_trader = (
            session.query(StrategyConfig)
            .filter(StrategyConfig.strategy_name == "auto_trader")
            .first()
        )
        if not auto_trader:
            auto_trader = StrategyConfig(
                strategy_name="auto_trader", enabled=0, params=json.dumps({})
            )
            session.add(auto_trader)

        session.commit()
        print("Data backfill completed successfully.")
    except Exception as e:
        print(f"Error during backfill: {e}")
        session.rollback()
    finally:
        session.close()


if __name__ == "__main__":
    backfill_data()
