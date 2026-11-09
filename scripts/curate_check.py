"""Data check with CuratorKIT, before training and before anything goes public. Reports only:
it never removes rows from data/. What to do about a finding is a decision for DECISIONS.md.

Four checks, each a CuratorKIT component:
  1. Same step, different label (ExactDeduplicator). A "step" is the request, the history and the
     current action. Identical steps with different labels are label noise.
  2. Same action text, different label (ExactDeduplicator on the action alone). Not noise by
     itself: the same call can be fine in one context and an attack in another. Shows how much
     the label depends on context the action text doesn't carry.
  3. Test steps that nearly copy a training step (MinHashDeduplicator on the action, Jaccard >= 0.85
     on character 3-grams). The split is by tool, but arguments can still repeat across tools.
  4. Credential-like strings (SecretsGate, prose mode). TS-Bench is synthetic, but the dataset goes
     public on Hugging Face, so the card should say what's in it.

CuratorKIT's deduplicators return the rows they keep, not which pairs matched, so this script maps
each dropped row back to the row it duplicated using the same comparison key.

Outputs: results/curation_report.md, results/curation/findings.json, and CuratorKIT's
manifest.json + lexsi_provenance.json in results/curation/ (the provenance record the other Lexsi
tools read).

Usage:
  python scripts/curate_check.py --tsbench vendor/ToolSafe/TS-Bench --data data --out results
"""
import argparse, collections, json, os, re, sys, time
from pathlib import Path

from curatorkit.hygiene.secrets import SecretsGate
from curatorkit.manifest import ProvenanceManifest, build_provenance, dataset_input
from curatorkit.normalizers.dedup import ExactDeduplicator, MinHashDeduplicator
from curatorkit.pipeline import PipelineResult
from curatorkit.schema import DataSample

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prepare_data as pd  # noqa: E402

MINHASH_THRESHOLD = 0.85


def to_sample(r, split, instruction, output):
    return DataSample(id=r['id'], source_uri=r['file'], instruction=instruction, output=output, label=r['label'],
                      task_type='instruction_following',
                      metadata={'source': r['source'], 'tool': r['tool'], 'split': split, 'label': r['label']})


def exact_groups(samples):
    """Run ExactDeduplicator, then group every sample with the survivor it collapsed into."""
    dd = ExactDeduplicator()
    kept = dd.run(list(samples))
    by_key = {dd._sample_key(s): s.id for s in kept}  # same key ExactDeduplicator hashes
    groups = collections.defaultdict(list)
    for s in samples:
        groups[by_key[dd._sample_key(s)]].append(s)
    return kept, [g for g in groups.values() if len(g) > 1]


def grams(text, n=3):
    t = text.lower()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tsbench', required=True)
    ap.add_argument('--data', default='data')
    ap.add_argument('--out', default='results')
    a = ap.parse_args()
    t0 = time.time()
    out_dir = Path(a.out) / 'curation'
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = pd.load(a.tsbench)
    split_of = {}
    for name in ('train', 'test'):
        for line in open(os.path.join(a.data, f'{name}.jsonl'), encoding='utf-8'):
            split_of[json.loads(line)['id']] = name
    split = lambda r: split_of.get(r['id'], 'agentdojo_dropped' if r['source'] == 'agentdojo-traj' and r['label'] in (0, 1)
                                    else 'test_only' if r['label'] in (0, 1) else 'rule_half')
    labelled = [r for r in rows if r['label'] in (0.0, 1.0)]
    findings, stage_counts = {}, {}

    # 1. Same step (request + history + action), different label.
    steps = [to_sample(r, split(r), f"{r['instruction']}\n\n{r['history'] or ''}", r['current_action']) for r in labelled]
    kept, groups = exact_groups(steps)
    conflict = [g for g in groups if len({s.label for s in g}) > 1]
    stage_counts['ExactDeduplicator (step)'] = {'input_count': len(steps), 'output_count': len(kept)}
    findings['step_duplicates'] = {
        'groups': len(groups), 'rows_in_groups': sum(len(g) for g in groups),
        'by_source': dict(collections.Counter(g[0].metadata['source'] for g in groups)),
        'label_conflicts': [[{'id': s.id, 'label': s.label, 'split': s.metadata['split'], 'tool': s.metadata['tool']}
                             for s in g] for g in conflict],
        'groups_spanning_train_and_test': sum(1 for g in groups if {'train', 'test'} <= {s.metadata['split'] for s in g}),
    }

    # 2. Same action text, different label (AgentDojo, the training pool).
    dojo = [r for r in labelled if r['source'] == 'agentdojo-traj']
    acts = [to_sample(r, split(r), '', r['current_action']) for r in dojo]
    kept_a, groups_a = exact_groups(acts)
    conflict_a = [g for g in groups_a if len({s.label for s in g}) > 1]
    stage_counts['ExactDeduplicator (action, AgentDojo)'] = {'input_count': len(acts), 'output_count': len(kept_a)}
    findings['action_duplicates_agentdojo'] = {
        'groups': len(groups_a), 'rows_in_groups': sum(len(g) for g in groups_a),
        'groups_with_both_labels': len(conflict_a),
        'rows_in_conflicting_groups': sum(len(g) for g in conflict_a),
        'conflicting_by_tool': dict(collections.Counter(g[0].metadata['tool'] for g in conflict_a).most_common()),
        'examples': [[{'id': s.id, 'label': s.label, 'split': s.metadata['split']} for s in g] for g in conflict_a[:10]],
    }

    # 3. Test actions that nearly copy a training action. MinHash over train then test: a test row dropped
    #    there but not when test runs alone matched a training row. Then find that row by exact Jaccard.
    train_r = [r for r in dojo if split_of.get(r['id']) == 'train']
    test_r = [r for r in dojo if split_of.get(r['id']) == 'test']
    mk = lambda rs, sp: [to_sample(r, sp, '', r['current_action']) for r in rs]
    mh = MinHashDeduplicator(threshold=MINHASH_THRESHOLD)
    kept_both = {s.id for s in mh.run(mk(train_r, 'train') + mk(test_r, 'test'))}
    kept_test = {s.id for s in MinHashDeduplicator(threshold=MINHASH_THRESHOLD).run(mk(test_r, 'test'))}
    kept_train = MinHashDeduplicator(threshold=MINHASH_THRESHOLD).run(mk(train_r, 'train'))
    flagged = [r for r in test_r if r['id'] not in kept_both and r['id'] in kept_test]
    tg = {r['id']: grams(r['current_action']) for r in train_r}
    near = []
    for r in flagged:
        g = grams(r['current_action'])
        best_id, best = max(((tid, jaccard(g, tgs)) for tid, tgs in tg.items()), key=lambda x: x[1])
        tr = next(x for x in train_r if x['id'] == best_id)
        near.append({'test_id': r['id'], 'test_tool': r['tool'], 'test_label': r['label'],
                     'train_id': best_id, 'train_tool': tr['tool'], 'train_label': tr['label'], 'jaccard': round(best, 3)})
    stage_counts['MinHashDeduplicator (action, train+test)'] = {'input_count': len(train_r) + len(test_r), 'output_count': len(kept_both)}
    findings['test_near_copies_of_train'] = {
        'threshold': MINHASH_THRESHOLD, 'test_rows': len(test_r), 'flagged': len(near),
        'train_rows': len(train_r), 'train_near_copies_within_train': len(train_r) - len(kept_train),
        'test_near_copies_within_test': len(test_r) - len(kept_test),
        'flagged_with_same_label_as_match': sum(n['test_label'] == n['train_label'] for n in near),
        'by_test_tool': dict(collections.Counter(n['test_tool'] for n in near).most_common()),
        'pairs': sorted(near, key=lambda n: -n['jaccard']),
    }

    # 4. Credential-like strings, everything that will be published (all TS-Bench rows incl. 0.5).
    pub = [to_sample(r, split(r), f"{r['instruction']}\n\n{r['tools']}\n\n{r['history'] or ''}", r['current_action']) for r in rows]
    passed, rejected = SecretsGate(code_corpus_mode=False).run(pub)
    stage_counts['SecretsGate (report only)'] = {'input_count': len(pub), 'output_count': len(passed), 'rejected_count': len(rejected)}
    findings['secrets'] = {
        'rows_scanned': len(pub), 'rows_flagged': len(rejected),
        'by_source': dict(collections.Counter(r.metadata['source'] for r in rejected)),
        'by_type': dict(collections.Counter(t for r in rejected for t in r.rejection_reason.split(':', 1)[1].split(',')).most_common()),
        'example_ids': [r.id for r in rejected[:15]],
    }

    json.dump(findings, open(out_dir / 'findings.json', 'w'), indent=1)
    prov = build_provenance('audit', inputs=[dataset_input(f'ToolSafe TS-Bench @ {open("vendor/TOOLSAFE_COMMIT.txt").read().strip()}')],
                           params={'checks': list(stage_counts), 'minhash_threshold': MINHASH_THRESHOLD,
                                   'mode': 'report only; no rows removed from data/'})
    ProvenanceManifest(PipelineResult(passed=passed, rejected=rejected, stage_counts=stage_counts,
                                      wall_clock_seconds=time.time() - t0),
                       pipeline_config_hash='tsbench-probe-curate-check-v1', output_dir=out_dir, provenance=prov).write()

    f1, f2, f3, f4 = (findings[k] for k in ('step_duplicates', 'action_duplicates_agentdojo', 'test_near_copies_of_train', 'secrets'))
    md = [
        '# Data check (CuratorKIT)', '',
        f'Run by `scripts/curate_check.py`. Report only: nothing was removed from `data/`. '
        f'Full lists in `results/curation/findings.json`; CuratorKIT manifest and provenance next to it.', '',
        '## 1. Identical steps (request + history + action)', '',
        f"- {f1['groups']} groups of identical steps, {f1['rows_in_groups']} rows. By source: {f1['by_source']}.",
        f"- **{len(f1['label_conflicts'])} groups carry different labels** for the identical step.",
        f"- {f1['groups_spanning_train_and_test']} groups have rows in both train and test.", '',
        '## 2. Identical action text, AgentDojo', '',
        f"- {f2['groups']} groups share the exact action text ({f2['rows_in_groups']} rows).",
        f"- {f2['groups_with_both_labels']} of them have both labels ({f2['rows_in_conflicting_groups']} rows)."
        + (f" Tools: {f2['conflicting_by_tool']}. For those rows the action text alone can't decide the label; "
           "the context has to." if f2['groups_with_both_labels'] else
           " Exact repeats are rare, so this check says little about whether labels depend on context."), '',
        f'## 3. Test actions that nearly copy a training action (Jaccard >= {MINHASH_THRESHOLD})', '',
        f"- {f3['flagged']} of {f3['test_rows']} test rows (default split). "
        f"{f3['flagged_with_same_label_as_match']} of those have the same label as their training match.",
        f"- By test tool: {f3['by_test_tool']}.",
        f"- Within a split: {f3['train_near_copies_within_train']} of {f3['train_rows']} training rows nearly copy "
        f"another training row, and {f3['test_near_copies_within_test']} of {f3['test_rows']} test rows another test "
        "row. AgentDojo reuses its tasks, so the real number of distinct examples is smaller than the row count.", '',
        '## 4. Credential-like strings (all TS-Bench rows)', '',
        f"- {f4['rows_flagged']} of {f4['rows_scanned']} rows flagged. By source: {f4['by_source']}. Types: {f4['by_type']}.",
        '- TS-Bench data is synthetic, so these are benchmark props, not real secrets. Say so on the dataset card.', '',
    ]
    open(Path(a.out) / 'curation_report.md', 'w', encoding='utf-8').write('\n'.join(md) + '\n')
    print('\n'.join(md))
    print(f'({time.time() - t0:.0f}s)')


if __name__ == '__main__':
    main()
