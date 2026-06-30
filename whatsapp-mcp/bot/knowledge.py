"""
knowledge.py - Static knowledge base loader.
"""

import os

def load_knowledge() -> str:
    """Load the static knowledge base from knowledge.txt."""
    knowledge_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'knowledge.txt')
    try:
        with open(knowledge_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        print("[memory] knowledge.txt not found, using empty knowledge base.")
        return ""
