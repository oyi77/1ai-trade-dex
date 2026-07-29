---
sidebar_position: 6
---

# Extending PolyEdge

The system's modular design makes it easy to add new features, strategies, and integrations.

## Adding a New Trading Strategy

Strategies are defined in the `backend/strategies/` directory and inherit from the `BaseStrategy` class.

1. **Create a Module**: Define a new Python file in `backend/strategies/` (e.g., `new_strategy.py`).
2. **Inherit from BaseStrategy**: Implement the `generate_signals()` method.
3. **Register the Strategy**: Add an entry to `backend/strategies/registry.py` to enable it in the system.
4. **Configure Schedules**: Define when the strategy should run in `backend/core/scheduling/scheduler/`.

## Adding a New API Endpoint

The backend is modularized into domain-specific routers.

1. **Select a Router**: Determine which module in `backend/api/` (e.g., `trading.py`, `markets.py`) your endpoint belongs in.
2. **Define the Route**: Use the FastAPI `@router.get()`, `@router.post()`, etc., decorators to add your logic.
3. **Update Models**: If needed, create new Pydantic models in `backend/models/` for request and response validation.

## Adding a New Dashboard Component

The frontend is built with React and uses a modular component structure.

1. **Create a Component**: Define your UI in a new file in `frontend/src/components/` or a sub-directory.
2. **Add a Hook**: If your component requires data from the backend, add a new TanStack Query hook in `frontend/src/hooks/`.
3. **Integrate**: Add your component to the appropriate page, such as `Dashboard.tsx` or `Admin.tsx`.

## Adding a New Data Source

Data ingestion is handled by dedicated clients in `backend/data/`.

1. **Create a Client**: Define a new class to handle communication with the external API or service.
2. **Implement Fetching**: Add methods for retrieving and parsing the data into a standard format.
3. **Configure Settings**: Add any required API keys or settings to `backend/config.py`.
4. **Integrate with Strategies**: Use the new data client within your trading strategy's logic.

## Plugin Points and Patterns

PolyEdge uses several patterns to facilitate extensions:
- **StrategyContext**: Provides strategies with access to market data, risk limits, and AI ensemble logic.
- **EventBus**: Allows decoupled communication between backend modules via pub/sub events.
- **AbstractQueue**: Defines a consistent interface for the job queue, allowing easy swaps between SQLite and Redis.
- **HandleErrors Decorator**: Provides uniform logging and error responses across API routes.
