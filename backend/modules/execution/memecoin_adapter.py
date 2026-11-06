class MemecoinExecAdapter:
    def __init__(self, enabled=False, halted=True):
        self.enabled = enabled
        self.halted = halted

    async def execute(self, payload=None):
        return {"status": "NOT_EXECUTED", "reason": "EXECUTION_DISABLED", "primitive": "MEMO", "memo": None, "success": False}


MemecoinDEXAdapter = MemecoinExecAdapter
MemecoinAdapter = MemecoinExecAdapter
