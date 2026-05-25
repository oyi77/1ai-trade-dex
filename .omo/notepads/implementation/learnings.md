# Wave 8 Implementation Learnings

## Genome Domain Models
- Successfully implemented all Pydantic v2 models from specification
- Used `Field` with validation constraints (ge, le, default_factory)
- Used `Literal` types for enumerated string values
- Implemented `DeathCertificate` as dataclass as specified
- All models properly serialize to JSON for database storage

## Mutation Engine
- Implemented adaptive mutation rates based on fitness scores
- Created 5 mutation types: hyperparameter tweak, indicator swap, timeframe shift, risk model reassignment, chromosome addition
- Fixed issue with Pydantic object handling - had to use `hasattr()` checks instead of `.get()` method
- Ensured proper deep copying with fresh UUID generation for mutated genomes
- Preserved lineage information correctly

## Crossover Engine
- Implemented regime-weighted chromosome selection
- Fixed issue where mutation was overwriting crossover lineage creator
- Added proper parent selection logic for different market regimes
- Ensured child genomes start as DRAFT stage

## Fitness Calculation
- Implemented exact formula from specification
- Added normalize helper function
- Properly handles edge cases (insufficient trades, clamping)
- Returns scores between 0.0 (worst) and 1.0 (best)

## Initial Population Seeding
- Created 9 founding archetypes with specific traits
- Implemented 20% diversity injection for numeric genes
- All genomes properly initialized with synthesis creator and DRAFT stage
- Each archetype has unique characteristics suitable for different trading strategies

## Testing
- Comprehensive test coverage for all components
- Fixed issues with Pydantic model handling in tests
- All 43 tests passing
- Tests cover validation, edge cases, and integration scenarios

## Key Technical Challenges
1. **Pydantic vs Dict Handling**: Had to carefully handle Pydantic objects vs dict access patterns
2. **Deep Copying**: Ensured proper genome copying with fresh UUIDs for mutations
3. **Lineage Preservation**: Fixed crossover lineage being overwritten by mutation
4. **Type Safety**: Ensured all Literal types and Field constraints work correctly

## Best Practices Applied
- Used Pydantic v2 modern syntax
- Implemented proper validation constraints
- Created comprehensive test suites
- Handled edge cases gracefully
- Maintained clean separation between domain models and database layer