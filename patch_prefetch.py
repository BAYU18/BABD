import ast

path = ".babd/researcher/gpt-researcher/gpt_researcher/skills/researcher.py"
with open(path) as f:
    src = f.read()

old = '''                    if url and raw_content and len(raw_content) > 100:
                        # Retriever already fetched full content (e.g. PubMed Central)
                        prefetched_content.append({
                            "url": url,
                            "raw_content": raw_content,
                        })
                        self.researcher.add_research_sources([{"url": url}])'''

new = '''                    if url and raw_content and len(raw_content) > 100:
                        # Retriever already fetched full content (e.g. PubMed Central,
                        # SearXNG). Carry the title through too, and expose "source" so
                        # prompt_family.pretty_print_docs() renders "Source: <url>" instead
                        # of "Source: None" (which made the writer hallucinate example.com).
                        title = result.get("title") or result.get("name") or ""
                        prefetched_content.append({
                            "url": url,
                            "source": url,
                            "title": title,
                            "raw_content": raw_content,
                        })
                        self.researcher.add_research_sources([{"url": url, "title": title, "source": url}])'''

assert old in src, "anchor not found"
src = src.replace(old, new, 1)

with open(path, "w") as f:
    f.write(src)
ast.parse(src)
print("SYNTAX OK")
print("patched:", '"source": url' in src)
