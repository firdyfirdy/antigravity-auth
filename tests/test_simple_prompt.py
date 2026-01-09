"""
Test Simple Prompt

Basic test to verify the Antigravity authentication and API integration works.
"""

import asyncio
import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from antigravity_auth import AntigravityService, NoAccountsError


class TestSimplePrompt:
    """Test basic prompt functionality."""
    
    def test_service_initialization(self):
        """Test that the service initializes correctly."""
        service = AntigravityService(model="gemini-3-pro")
        assert service.model == "gemini-3-pro"
    
    def test_get_accounts_empty(self):
        """Test getting accounts when none configured."""
        service = AntigravityService()
        accounts = service.get_accounts()
        # May be empty or have accounts depending on system state
        assert isinstance(accounts, list)
    
    @pytest.mark.asyncio
    async def test_generate_no_accounts(self):
        """Test that generate fails gracefully with no accounts."""
        service = AntigravityService()
        
        # Clear any existing accounts for this test
        from antigravity_auth.storage import load_accounts
        storage = load_accounts()
        
        if not storage or not storage.accounts:
            with pytest.raises(NoAccountsError):
                await service.generate(prompt="Test")


class TestLiveIntegration:
    """
    Live integration tests - only run when accounts are configured.
    
    Run with: pytest tests/test_simple_prompt.py -k live -v
    """
    
    @pytest.fixture
    def service(self):
        """Get an AntigravityService instance."""
        return AntigravityService(model="gemini-3-pro")
    
    @pytest.fixture
    def has_accounts(self, service):
        """Check if accounts are configured."""
        return len(service.get_accounts()) > 0
    
    @pytest.mark.asyncio
    async def test_live_simple_prompt(self, service, has_accounts):
        """Test a simple prompt with the live API."""
        if not has_accounts:
            pytest.skip("No accounts configured")
        
        response = await service.generate(
            prompt="What is 2 + 2? Answer with just the number.",
        )
        
        assert response is not None
        assert len(response) > 0
        assert "4" in response
    
    @pytest.mark.asyncio
    async def test_live_with_system_prompt(self, service, has_accounts):
        """Test a prompt with system instruction."""
        if not has_accounts:
            pytest.skip("No accounts configured")
        
        response = await service.generate(
            prompt="What is the capital of France?",
            system_prompt="You are a geography expert. Be concise.",
        )
        
        assert response is not None
        assert "Paris" in response
    
    def test_live_sync_prompt(self, service, has_accounts):
        """Test synchronous prompt generation."""
        if not has_accounts:
            pytest.skip("No accounts configured")
        
        response = service.generate_sync(
            prompt="Name one color of the rainbow.",
        )
        
        assert response is not None
        assert len(response) > 0


if __name__ == "__main__":
    # Quick manual test
    print("Testing AntigravityService...")
    
    service = AntigravityService(model="gemini-3-pro")
    
    accounts = service.get_accounts()
    print(f"Found {len(accounts)} account(s)")
    
    if accounts:
        print("\nTesting simple prompt...")
        try:
            response = service.generate_sync(
                prompt="What is 2 + 2? Answer in one word.",
            )
            print(f"Response: {response}")
            print("\n✅ Test passed!")
        except Exception as e:
            print(f"❌ Error: {e}")
    else:
        print("\nNo accounts configured. Run 'antigravity auth login' first.")
