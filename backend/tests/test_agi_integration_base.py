"""Base class for AGI integration tests — shadow mode enforcement, risk gates, KG integrity."""


class AGIIntegrationBase:
    def assert_shadow_mode_enforced(self, settings):
        assert settings.SHADOW_MODE is True, "SHADOW_MODE must be True in AGI tests"

    def assert_risk_manager_gates_active(self, risk_decision):
        assert risk_decision.allowed is not None, "RiskManager must produce a decision"
        if not risk_decision.allowed:
            assert risk_decision.reason, "RiskManager rejection must have a reason"

    def assert_kg_data_not_corrupted(self, kg, entity_id):
        entity = kg.get_entity(entity_id)
        if entity is not None:
            assert isinstance(
                entity.properties, dict
            ), "KG entity properties must be dict"
            assert entity.entity_type, "KG entity must have entity_type"
            assert entity.entity_id, "KG entity must have entity_id"
