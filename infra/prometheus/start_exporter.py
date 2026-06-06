import sys
sys.path.insert(0, '/app')
from src.collector.mock_backend import register_mock_collector
register_mock_collector('config/scenarios.yaml', port=8000)
