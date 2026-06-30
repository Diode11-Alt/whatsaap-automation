import re
import json
import os
import sys

def parse_whatsapp_chat(filepath, your_name):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Regex for WhatsApp export format: [dd/mm/yyyy, hh:mm:ss] Name: Message
    pattern = re.compile(r'^\[(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}[, ]+\d{1,2}:\d{2}:\d{2}(?: [AP]M)?)\] (.*?): (.*)')
    
    messages = []
    current_msg = None

    for line in lines:
        match = pattern.match(line)
        if match:
            if current_msg:
                messages.append(current_msg)
            sender = match.group(2).strip()
            text = match.group(3).strip()
            role = "assistant" if sender.lower() == your_name.lower() else "user"
            current_msg = {"role": role, "content": text, "sender": sender}
        elif current_msg:
            current_msg["content"] += "\n" + line.strip()

    if current_msg:
        messages.append(current_msg)

    # Convert to conversations
    conversations = []
    current_convo = {"messages": []}
    
    for msg in messages:
        # Very basic split: if the same role speaks consecutively, merge them
        if not current_convo["messages"] or current_convo["messages"][-1]["role"] != msg["role"]:
            current_convo["messages"].append({"role": msg["role"], "content": msg["content"]})
        else:
            current_convo["messages"][-1]["content"] += "\n" + msg["content"]
            
        # Group into pairs (User -> Assistant)
        if len(current_convo["messages"]) >= 2 and current_convo["messages"][-1]["role"] == "assistant":
            # Add system prompt
            sys_msg = {"role": "system", "content": "You are Sujal. Reply naturally."}
            final_convo = {"messages": [sys_msg] + current_convo["messages"][-2:]}
            conversations.append(final_convo)
            current_convo = {"messages": []}

    return conversations

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python export_to_jsonl.py <path_to_chat.txt> <your_exact_whatsapp_name>")
        sys.exit(1)
        
    in_file = sys.argv[1]
    name = sys.argv[2]
    out_file = "finetune_dataset.jsonl"
    
    convos = parse_whatsapp_chat(in_file, name)
    
    with open(out_file, 'w', encoding='utf-8') as f:
        for c in convos:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
            
    print(f"✅ Exported {len(convos)} conversation pairs to {out_file}!")
    print("You can now upload this file to Google Colab (Unsloth) for fine-tuning!")
