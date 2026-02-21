from hooks.scripts.memory_judge import judge_candidates

candidates = [{"tags": ["a", ["b"]]}]
judge_candidates("prompt", candidates, include_context=False)
