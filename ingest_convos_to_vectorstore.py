from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, ServiceContext
from llama_index.llms.ollama import Ollama
from llama_index.core.node_parser import SimpleNodeParser
from llama_index.core.embeddings import resolve_embed_model
from llama_index.vector_stores.faiss import FaissVectorStore
from llama_index.core import StorageContext, Document
import json
import os

# Load JSONL conversations
def load_jsonl(path):
    docs = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            docs.append(Document(text=data['document']))
    return docs

def main():
    print("🚀 Loading messages from JSONL...")
    docs = load_jsonl("conversations.jsonl")

    print("💡 Setting up Ollama + Embedding...")
    llm = Ollama(model="mistral")  # or your custom model
    embed_model = resolve_embed_model("local:BAAI/bge-small-en")  # switch to "local" for ollama's embed model

    service_context = ServiceContext.from_defaults(llm=llm, embed_model=embed_model)

    print("📦 Creating vector index...")
    vector_store = FaissVectorStore.from_persist_dir("./vectorstore")
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_documents(docs, storage_context=storage_context, service_context=service_context)

    print("💾 Persisting vectorstore...")
    index.storage_context.persist(persist_dir="./vectorstore")
    print("✅ Done! Your convos are now embedded and ready to RAG.")

if __name__ == "__main__":
    main()

