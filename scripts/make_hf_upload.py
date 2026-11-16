"""Stage the four Hugging Face repos in work/hf/, and upload them with --upload.

  aya-probe-gate-tiny-aya-global   model    probes and steering vectors (CC-BY-NC-4.0)
  aya-probe-gate-aya-expanse-8b    model    the same for Expanse
  aya-probe-gate-data              dataset  data/ (Apache-2.0)
  aya-probe-gate-runs              dataset  results/ without weights (MIT)

Only files git knows about (tracked, or new and not ignored) are staged, so work/, vendor/ToolSafe
and memo files can never go up. Cards come from hf/*.md.

  python scripts/make_hf_upload.py                      # stage and list, nothing leaves the machine
  python scripts/make_hf_upload.py --upload --user NAME # create the repos and two collections, upload
"""
import argparse, os, shutil, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE = os.path.join(ROOT, 'work', 'hf')
WEIGHTS = ('.npz', '.pt')

MODELS = {
    'tiny-aya-global': {
        'BASE': 'CohereLabs/tiny-aya-global', 'LABEL': 'Tiny Aya Global', 'PROBE_LAYER': '19',
        'files': {
            'probe_v1/probe_best.npz': 'results/followup-tiny-aya-global/gate-tiny-aya-global/probe/probe_best.npz',
            'probe_v1/probe_pre.npz': 'results/followup-tiny-aya-global/gate-tiny-aya-global/probe/probe_pre.npz',
            'probe_v2/probe_best.npz': 'results/probe-v2-tiny-aya-global/probe/probe_best.npz',
            'cast/steer.pt': 'results/gate-tiny-aya-global/steer.pt',
            'cast/steer.json': 'results/gate-tiny-aya-global/steer.json',
            'steer_back_v1/redirect_vectors.pt': 'results/followup-tiny-aya-global/calib-tiny-aya-global/redirect_vectors.pt',
            'steer_back_v1/redirect.json': 'results/followup-tiny-aya-global/calib-tiny-aya-global/redirect.json',
            'steer_pairs/redirect_vectors.pt': 'results/steer-v2-tiny-aya-global/redirect_vectors.pt',
            'steer_pairs/steer_vectors.npz': 'results/steer-v2-tiny-aya-global/steer_vectors.npz',
            'steer_pairs/steer_vectors.json': 'results/steer-v2-tiny-aya-global/steer_vectors.json',
            'steer_pairs_gb10/redirect_vectors.pt': 'results/steer-v2-tiny-aya-global/gb10/redirect_vectors.pt',
            'steer_pairs_gb10/steer_vectors.npz': 'results/steer-v2-tiny-aya-global/gb10/steer_vectors.npz',
            'steer_pairs_gb10/steer_vectors.json': 'results/steer-v2-tiny-aya-global/gb10/steer_vectors.json',
            'steer_pairs_gb10_extra_layers/redirect_vectors.pt': 'results/steer-v3-tiny-aya-global/extra-layers/redirect_vectors.pt',
            'steer_pairs_gb10_extra_layers/steer_vectors.npz': 'results/steer-v3-tiny-aya-global/extra-layers/steer_vectors.npz',
            'steer_pairs_gb10_extra_layers/steer_vectors.json': 'results/steer-v3-tiny-aya-global/extra-layers/steer_vectors.json',
            'settings/round2.json': 'results/steer-v2-calib-tiny-aya-global/redirect.json',
            'settings/round3.json': 'results/steer-v3-calib-tiny-aya-global/redirect.json',
        },
        'EXTRA_ROWS': "| `steer_pairs_gb10/`, `steer_pairs_gb10_extra_layers/` | The same vectors rebuilt on a second GPU for round 3 "
                      "(layers 11, 15, 19, then 13, 17, 21). Round 3's setting points at these. |\n",
        'RESULTS': "- One step, 232 held-out AgentDojo steps: attacks through 20% with no gate, 3% with a hard block, **3% with steer "
                   "back + check again**, which stops 7% of harmless steps against the block's 12%.\n"
                   "- Reading the draft, the probe ranks the steps where the model obeyed the attacker at AUROC 0.94; reading the prompt, 0.38.\n"
                   "- Whole tasks in a simulator (35 attacked tasks, probe v2): a plain retry prompt finishes 0 with no attack, one steering "
                   "strength 2, **escalating steering 15** (p = 0.0001), no attack through.",
    },
    'aya-expanse-8b': {
        'BASE': 'CohereLabs/aya-expanse-8b', 'LABEL': 'Aya Expanse 8B', 'PROBE_LAYER': '15',
        'files': {
            'probe_v1/probe_best.npz': 'results/gate-aya-expanse-8b/probe/probe_best.npz',
            'probe_v1/probe_pre.npz': 'results/gate-aya-expanse-8b/probe/probe_pre.npz',
            'probe_v2/probe_best.npz': 'results/probe-v2-aya-expanse-8b/probe/probe_best.npz',
            'cast/steer.pt': 'results/gate-aya-expanse-8b/steer.pt',
            'cast/steer.json': 'results/gate-aya-expanse-8b/steer.json',
            'steer_back_v1/redirect_vectors.pt': 'results/gate-aya-expanse-8b/redirect_vectors.pt',
            'steer_back_v1/redirect.json': 'results/gate-aya-expanse-8b/redirect.json',
            'steer_pairs/redirect_vectors.pt': 'results/steer-v2-aya-expanse-8b/redirect_vectors.pt',
            'steer_pairs/steer_vectors.npz': 'results/steer-v2-aya-expanse-8b/steer_vectors.npz',
            'steer_pairs/steer_vectors.json': 'results/steer-v2-aya-expanse-8b/steer_vectors.json',
            'steer_pairs_extra_layers/redirect_vectors.pt': 'results/steer-v3-aya-expanse-8b/extra-layers/redirect_vectors.pt',
            'steer_pairs_extra_layers/steer_vectors.npz': 'results/steer-v3-aya-expanse-8b/extra-layers/steer_vectors.npz',
            'steer_pairs_extra_layers/steer_vectors.json': 'results/steer-v3-aya-expanse-8b/extra-layers/steer_vectors.json',
            'settings/round2.json': 'results/steer-v2-calib-aya-expanse-8b/redirect.json',
            'settings/round3.json': 'results/steer-v3-calib-aya-expanse-8b/redirect.json',
        },
        'EXTRA_ROWS': "| `steer_pairs_extra_layers/` | Round 3's added layers (9, 10, 12, 13), same pairs. Round 3's setting (layer 10) uses these. |\n",
        'RESULTS': "- One step, 234 held-out AgentDojo steps: attacks through 15% with no gate, 5% with a hard block, **5% with steer "
                   "back + check again**, which stops 8% of harmless steps against the block's 12%.\n"
                   "- Reading the draft, the probe ranks the steps where the model obeyed the attacker at AUROC 0.91; reading the prompt, 0.66.\n"
                   "- Whole tasks in a simulator (60 attacked tasks, probe v2): a plain retry prompt finishes 49 with no attack, one steering "
                   "strength 49, **escalating steering 57** (p = 0.039), no attack through, all 60 clean tasks finished.",
    },
}


def known(folder):
    out = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', folder], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.splitlines()
    return [f for f in out if os.path.exists(os.path.join(ROOT, f))]


def put(src, repo, dst):
    d = os.path.join(STAGE, repo, dst)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copyfile(os.path.join(ROOT, src), d)


def card(name, repo, user, **fields):
    text = open(os.path.join(ROOT, 'hf', name), encoding='utf-8').read().replace('{USER}', user)
    for k, v in fields.items():
        text = text.replace('{' + k + '}', v)
    with open(os.path.join(STAGE, repo, 'README.md'), 'w', encoding='utf-8') as f:
        f.write(text)


def stage(user):
    shutil.rmtree(STAGE, ignore_errors=True)
    tracked = set(known('results'))
    for name, m in MODELS.items():
        repo = f'aya-probe-gate-{name}'
        for dst, src in m['files'].items():
            if src not in tracked:
                raise SystemExit(f'not in git: {src}')
            put(src, repo, dst)
        card('model_card.md', repo, user, **{k: v for k, v in m.items() if k != 'files'})
    for f in known('data'):
        put(f, 'aya-probe-gate-data', os.path.relpath(f, 'data'))
    for f in tracked:
        if not f.endswith(WEIGHTS + ('.zip',)) and os.path.basename(f) != 'memo.jsonl':
            put(f, 'aya-probe-gate-runs', os.path.relpath(f, 'results'))
    for repo, name in (('aya-probe-gate-data', 'data_card.md'), ('aya-probe-gate-runs', 'runs_card.md')):
        put('NOTICE', repo, 'NOTICE')
        card(name, repo, user)
    for repo in sorted(os.listdir(STAGE)):
        files = [os.path.join(d, f) for d, _, fs in os.walk(os.path.join(STAGE, repo)) for f in fs]
        print(f'{repo}: {len(files)} files, {sum(os.path.getsize(f) for f in files) / 1e6:.1f} MB')


def upload(user):
    from huggingface_hub import HfApi
    api = HfApi()
    kinds = {'aya-probe-gate-tiny-aya-global': 'model', 'aya-probe-gate-aya-expanse-8b': 'model',
             'aya-probe-gate-data': 'dataset', 'aya-probe-gate-runs': 'dataset'}
    for repo, kind in kinds.items():
        rid = f'{user}/{repo}'
        api.create_repo(rid, repo_type=kind, private=False, exist_ok=True)
        api.upload_folder(folder_path=os.path.join(STAGE, repo), repo_id=rid, repo_type=kind,
                          commit_message='aya-probe-gate: Lexsi hackathon submission')
        print('uploaded', f"https://huggingface.co/{'datasets/' if kind == 'dataset' else ''}{rid}")
    for title, kind, desc in (('Aya probe gate: probes and steering vectors', 'model',
                               'Linear probes and steering vectors for Tiny Aya Global and Aya Expanse 8B (Lexsi hackathon, Track 2b #8).'),
                              ('Aya probe gate: data, logs and traces', 'dataset',
                               'Data splits, simulator task pools and every run\'s outputs (Lexsi hackathon, Track 2b #8).')):
        c = api.create_collection(title, namespace=user, description=desc, private=False, exists_ok=True)
        for repo, k in kinds.items():
            if k == kind:
                api.add_collection_item(c.slug, f'{user}/{repo}', item_type=kind, exists_ok=True)
        print('collection', f'https://huggingface.co/collections/{c.slug}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--user', default='YOUR_USERNAME')
    ap.add_argument('--upload', action='store_true')
    a = ap.parse_args()
    stage(a.user)
    if a.upload:
        if a.user == 'YOUR_USERNAME':
            ap.error('--upload needs --user')
        upload(a.user)


if __name__ == '__main__':
    main()
