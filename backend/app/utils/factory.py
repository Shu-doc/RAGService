from abc import ABC, abstractmethod
from typing import Optional, List
import os
from dotenv import load_dotenv

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_ollama import OllamaEmbeddings, ChatOllama

from app.core.logger_handler import logger

# 加载环境变量
load_dotenv()


class DashScopeEmbeddingsWrapper(Embeddings):
    """阿里云DashScope嵌入模型封装"""

    # DashScope 有效嵌入模型名（与 Ollama 命名不同，不通用 qwen 前缀）
    # 文档: https://help.aliyun.com/zh/model-studio/text-embedding
    VALID_MODELS = {
        'text-embedding-v1', 'text-embedding-v2',
        'text-embedding-v3', 'text-embedding-async-v1', 'text-embedding-async-v2',
    }

    def __init__(self, model_name: str = "text-embedding-v3", api_key: str = None):
        try:
            import dashscope
            self.dashscope = dashscope
            self.dashscope.api_key = api_key or os.getenv("ALIYUN_ACCESS_KEY_SECRET")
            # 如果配置的是 Ollama 风格模型名（如 qwen3-embedding），自动纠正为 DashScope 有效模型
            if model_name not in self.VALID_MODELS:
                logger.warning(
                    f"⚠️ 嵌入模型名 '{model_name}' 非 DashScope 标准模型，使用默认 text-embedding-v3"
                )
                self.model_name = "text-embedding-v3"
            else:
                self.model_name = model_name
        except ImportError:
            raise ImportError("需要安装 dashscope 库: pip install dashscope")

    def _call_api(self, text: str):
        """调用 DashScope TextEmbedding API，返回 embedding 向量"""
        resp = self.dashscope.TextEmbedding.call(
            model=self.model_name,
            input=text
        )
        if resp.status_code == 200:
            # DashScope 响应格式: output.embeddings[0].embedding (注意复数)
            embeddings = resp.output.get('embeddings', [])
            if embeddings and 'embedding' in embeddings[0]:
                return embeddings[0]['embedding']
            logger.error(f"阿里云嵌入响应格式异常: {resp.output}")
            return None
        else:
            logger.error(
                f"阿里云嵌入调用失败: status={resp.status_code}, "
                f"code={getattr(resp, 'code', 'N/A')}, "
                f"message={getattr(resp, 'message', 'N/A')}"
            )
            return None

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入文档"""
        results = []
        for i, text in enumerate(texts):
            vec = self._call_api(text)
            if vec is not None:
                results.append(vec)
            else:
                logger.error(f"阿里云嵌入失败 (第{i+1}/{len(texts)}段文本, 长度={len(text)})")
                results.append([])
        return results

    def embed_query(self, text: str) -> List[float]:
        """嵌入单个查询"""
        vec = self._call_api(text)
        if vec is not None:
            return vec
        logger.error("阿里云查询嵌入失败，返回空向量")
        return []


class BaseModelFactory(ABC):
    """基础模型工厂"""

    @abstractmethod
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """生成模型"""
        pass


class ChatModelFactory(BaseModelFactory):
    """聊天模型工厂 - 支持阿里云百炼和Ollama"""
    
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """根据LLM_TYPE生成对应的聊天模型"""
        llm_type = os.getenv("LLM_TYPE", "ALIYUN").upper()
        
        if llm_type == "OLLAMA":
            model_name = os.getenv("OLLAMA_MODEL_NAME", os.getenv("OLLAMA_CHAT_MODEL_NAME", "qwen3:7b"))
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            
            logger.info(f"📦 ChatModel 使用Ollama模型: {model_name}, 地址: {base_url}")
            
            return ChatOllama(
                model=model_name,
                base_url=base_url,
                streaming=True,
                top_p=0.7,
            )
        
        elif llm_type == "ALIYUN":
            model_name = os.getenv("ALIYUN_MODEL_NAME", os.getenv("CHAT_MODEL_NAME", "qwen3-max"))
            api_key = os.getenv("ALIYUN_ACCESS_KEY_SECRET")
            base_url = os.getenv("ALIYUN_BASE_URL")
            
            logger.info(f"📦 ChatModel 使用阿里云百炼模型: {model_name}")
            
            return ChatTongyi(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                streaming=True,
                top_p=0.7,
            )
        
        else:
            raise ValueError(f"不支持的LLM_TYPE: {llm_type}，可选值: ALIYUN, OLLAMA")


class EmbedModelFactory(BaseModelFactory):
    """嵌入模型工厂 - 支持Ollama和阿里云百炼"""
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """根据EMBED_MODEL_TYPE生成对应的嵌入模型"""
        embed_type = os.getenv("EMBED_MODEL_TYPE", "OLLAMA").upper()
        
        if embed_type == "OLLAMA":
            model_name = os.getenv("TEXT_EMBEDDING_MODEL_NAME", "qwen3-embedding:0.6b")
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            
            logger.info(f"📦 EmbedModel 使用Ollama嵌入模型: {model_name}, 地址: {base_url}")
            
            return OllamaEmbeddings(
                model=model_name,
                base_url=base_url
            )
        
        elif embed_type == "ALIYUN":
            model_name = os.getenv("ALIYUN_EMBED_MODEL_NAME", "qwen3-embedding")
            api_key = os.getenv("ALIYUN_ACCESS_KEY_SECRET")
            
            logger.info(f"📦 EmbedModel 使用阿里云嵌入模型: {model_name}")
            
            return DashScopeEmbeddingsWrapper(
                model_name=model_name,
                api_key=api_key
            )
        
        else:
            raise ValueError(f"不支持的EMBED_MODEL_TYPE: {embed_type}，可选值: OLLAMA, ALIYUN")


class RerankerModelFactory(BaseModelFactory):
    """重排序模型工厂 - 已废弃，使用CrossEncoder模型"""
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        """生成模型"""
        return None


chat_model = ChatModelFactory().generator()
embed_model = EmbedModelFactory().generator()
reranker_model = None
