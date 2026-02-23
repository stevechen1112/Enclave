from typing import Optional, Dict, Any
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import settings


class CoreAPIClient:
    """
    Core API 客戶端封裝
    負責與勞資法 AI 核心 API 通訊
    """
    
    def __init__(self):
        self.base_url = settings.CORE_API_URL
        self.service_token = settings.CORE_SERVICE_TOKEN
        self.timeout = 25.0  # seconds（Core API 需呼叫 GPT-4o，實測 8-15s）
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def chat(
        self,
        question: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        呼叫 Core API 的聊天接口
        
        Args:
            question: 用戶問題
            request_id: 請求 ID（用於追蹤）
        
        Returns:
            Core API 的回應結果
        """
        headers = {}
        if self.service_token:
            headers["Authorization"] = f"Bearer {self.service_token}"
        
        payload = {
            "question": question,
            "request_id": request_id
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Note: unihr Core uses /chat (not /v1/labor/chat)
                response = await client.post(
                    f"{self.base_url}/chat",
                    json={"message": question},  # unihr expects "message" not "question"
                    headers=headers
                )
                response.raise_for_status()
                return response.json()
        
        except httpx.TimeoutException:
            return {
                "status": "error",
                "answer": "Core API 響應超時，請稍後再試",
                "error": "timeout"
            }
        
        except httpx.HTTPError as e:
            return {
                "status": "error",
                "answer": "Core API 暫時不可用",
                "error": str(e)
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """檢查 Core API 健康狀態"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Note: unihr Core uses /health (not /v1/health)
                response = await client.get(f"{self.base_url}/health")
                response.raise_for_status()
                return {"status": "healthy", "data": response.json()}
        
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
