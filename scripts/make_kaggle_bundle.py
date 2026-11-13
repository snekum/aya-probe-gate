"""Zip what the Kaggle notebook needs, and nothing else.

Leaves out vendor/ToolSafe/scripts on purpose: process.py there has a hardcoded API key.
Upload the zip as a private Kaggle dataset; Kaggle unzips it.

Usage:
  python scripts/make_kaggle_bundle.py --out kaggle/tsbench-probe-bundle.zip
"""
import argparse, glob, os, re, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = ['probe_format.py', 'build_cache_inputs.py', 'cache_activations.py', 'train_probe.py',
           'gate.py', 'eval_gate.py', 'audit_gate.py', 'redirect_vector.py', 'threshold_curve.py',
           'prepare_data.py', 'score_probe.py', 'baselines.py', 'text_classifier.py',
           'recovery_env.py', 'recovery_tasks.py', 'recovery_run.py', 'recovery_report.py', 'recovery_selftest.py',
           'probe_v2_rows.py', 'train_probe_v2.py', 'probe_v2_report.py', 'probe_v2_selftest.py', 'run_probe_v2.py',
           'calibrate_v2.py']
# The task-recovery pilot reads the final Tiny Aya probe and steer-back vector from the repo, so its
# notebook needs no other notebook's output.
RECOVERY = ['results/followup-tiny-aya-global/gate-tiny-aya-global/probe/probe_best.npz',
            'results/followup-tiny-aya-global/calib-tiny-aya-global/redirect.json',
            'results/followup-tiny-aya-global/calib-tiny-aya-global/redirect_vectors.pt',
            # probe v2: Tiny Aya's one-step drafts (scored again on the fresh activations)
            'results/followup-tiny-aya-global/gate-tiny-aya-global/agent_outputs.jsonl',
            # probe v2's calibration rows: Tiny Aya's simple-pool episodes
            'results/recovery-simple-tiny-aya-global/episodes.jsonl']
KEY = re.compile(rb'sk-[A-Za-z0-9_\-]{20,}|api_key\s*=\s*["\'][A-Za-z0-9]')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'kaggle', 'tsbench-probe-bundle.zip'))
    a = ap.parse_args()
    files = [f'scripts/{s}' for s in SCRIPTS]
    files += [os.path.relpath(p, ROOT).replace('\\', '/') for p in glob.glob(os.path.join(ROOT, 'data', '*'))]
    files += ['results/baselines_seed_spread.json', 'vendor/TOOLSAFE_COMMIT.txt'] + RECOVERY
    files += [os.path.relpath(p, ROOT).replace('\\', '/')
              for p in glob.glob(os.path.join(ROOT, 'vendor', 'ToolSafe', 'TS-Bench', '**', '*'), recursive=True)
              if os.path.isfile(p)]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with zipfile.ZipFile(a.out, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in files:
            data = open(os.path.join(ROOT, f), 'rb').read()
            if KEY.search(data):
                raise SystemExit(f'{f} looks like it holds an API key; not bundling it')
            z.writestr(f, data)
    print(f'{len(files)} files, {os.path.getsize(a.out) / 1e6:.1f} MB -> {a.out}')


if __name__ == '__main__':
    main()
