import os
import json
import time
from datetime import datetime
from auto_reply import get_ai_reply

def read_json(filepath):
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except:
            return {}

def write_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

def generate_marketing_report():
    print("[Marketing Agent] Starting marketing intelligence workflow...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    vacancies_file = os.path.join(base_dir, 'vacancies.json')
    memory_file = os.path.join(base_dir, 'marketing_memory.json')
    reports_dir = os.path.join(base_dir, 'marketing_reports')
    os.makedirs(reports_dir, exist_ok=True)

    vacancies = read_json(vacancies_file)
    memory = read_json(memory_file)
    past_ideas = memory.get('past_ideas', [])

    if not vacancies:
        print("[Marketing Agent] No vacancies found. Aborting.")
        return None

    system_prompt = """You are an autonomous recruitment marketing strategist for an overseas recruitment company based in Nepal (Fortune First).
Your responsibility is to continuously discover what content performs best, understand current hiring demand, and transform company vacancies into viral social media content tailored for the Nepal audience.

Your execution MUST output a final Daily Deliverable report containing:
- Market Summary
- Latest recruitment trends
- Trending topics
- Country insights
- Vacancy opportunities
- 10 Reel ideas
- 10 TikTok ideas
- 5 Carousel ideas
- 5 Story ideas
- 5 Facebook posts
- 3 LinkedIn posts
- 5 YouTube Shorts
- Content calendar
- Best posting times
- Trending hashtags
- Trending audio suggestions
- Competitor observations
- Marketing recommendations
- Urgent opportunities
- Next actions

Each content idea should include Hook, Script, Caption, Thumbnail, Voiceover, B-roll suggestions, Hashtags, CTA, Posting time, Target audience, Platform.
Never repeat previous ideas.
"""
    
    # We will pass the vacancies and past ideas as context
    context = f"CURRENT VACANCIES:\n{json.dumps(vacancies, indent=2)}\n\nPAST IDEAS (DO NOT REPEAT THESE):\n"
    context += "\n".join(past_ideas[-20:])  # Last 20 ideas

    # The prompt explicitly asks the LLM to go through all phases internally and output the Phase 10 report.
    user_prompt = "Execute the 10-phase marketing intelligence protocol based on the provided vacancies. Do a deep analysis of destination countries, current TikTok/social media trends in Nepal, match trends with vacancies, use the creative engine, and output the ultimate Phase 10 Daily Deliverables Report in beautiful Markdown."

    print("[Marketing Agent] Calling LLM to generate report...")
    raw_response = get_ai_reply(system_prompt, [], f"{context}\n\n{user_prompt}", has_media=False)
    
    if not raw_response:
        print("[Marketing Agent] Failed to get response from AI.")
        return None

    # Strip out the <thought> tags if present
    import re
    cleaned_reply = re.sub(r'<thought>.*?</thought>', '', raw_response, flags=re.DOTALL).strip()
    if '<reply>' in cleaned_reply:
        match = re.search(r'<reply>(.*?)</reply>', cleaned_reply, re.DOTALL)
        if match:
            cleaned_reply = match.group(1).strip()
    
    # Save report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(reports_dir, f"report_{timestamp}.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(cleaned_reply)
    print(f"[Marketing Agent] Report generated at {report_path}")

    # Update memory (very simple extraction of hooks/ideas to avoid repeating)
    # We will just save a summary of what was generated to past_ideas
    summary_prompt = "Summarize the content ideas generated in this report into a few sentences so we don't repeat them tomorrow."
    summary_response = get_ai_reply(system_prompt, [], f"Report:\n{cleaned_reply}\n\n{summary_prompt}", has_media=False)
    if summary_response:
        clean_summary = re.sub(r'<thought>.*?</thought>', '', summary_response, flags=re.DOTALL).strip()
        clean_summary = re.sub(r'<reply>(.*?)</reply>', r'\1', clean_summary, flags=re.DOTALL).strip()
        past_ideas.append(f"{datetime.now().strftime('%Y-%m-%d')}: {clean_summary[:200]}")
        memory['past_ideas'] = past_ideas
        write_json(memory_file, memory)

    return report_path

if __name__ == "__main__":
    generate_marketing_report()
