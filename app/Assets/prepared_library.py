"""Transactional, cumulative source library for the offline outfit preparer.

The library owns copies of baked PNGs, not installed game files.  Build a
candidate, cook/stage its aggregate job, then commit only after that succeeds.
Failed preparation and unchecked outfits never erase an earlier good entry.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

PREFIX = '/Game/OutfitReversalPrepared/'
SCHEMA = 1


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _asset_path(value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return None
    package, _, name = value.partition('.')
    if '..' in package or '\\' in package or ':' in package:
        raise ValueError('Invalid prepared asset path: ' + value)
    return package + '.' + (name or package.rsplit('/', 1)[-1])


def _references(value):
    if isinstance(value, str):
        path = _asset_path(value)
        return {path} if path else set()
    if isinstance(value, dict):
        result = set()
        for item in value.values():
            result.update(_references(item))
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result.update(_references(item))
        return result
    return set()


def source_fingerprint(record):
    """Ignore display labels/file locations; include everything affecting variants."""
    original = record.get('original', {})
    return _digest({'variants': record['variants'], 'userConfigs': record.get('userConfigs', {}),
                    'ponyPhysics': original.get('PonyPhysics'), 'hiddenMats': original.get('HiddenMats')})


def _record_map(records):
    grouped = {}
    for record in records or []:
        grouped.setdefault(record['id'], []).append(record)
    valid, duplicates = {}, set()
    for fit_id, rows in grouped.items():
        if len(rows) != 1 or rows[0].get('duplicate'):
            duplicates.add(fit_id)
        else:
            valid[fit_id] = rows[0]
    return valid, duplicates


def prepared_value(entry):
    value = copy.deepcopy(entry['prepared'])
    if entry.get('history'):
        value['previousVersions'] = [copy.deepcopy(old['prepared']) for old in entry['history']]
    return value


class PreparedLibrary:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.index = self.root / 'index.json'
        self.state = _read(self.index) if self.index.is_file() else {
            'schemaVersion': SCHEMA, 'revision': 0, 'outfits': {}, 'assets': {}}
        if self.state.get('schemaVersion') != SCHEMA:
            raise ValueError('Unsupported prepared library schema; keep the existing library intact.')
        self._base_digest = _digest(self.state)

    def begin(self, records=None):
        return LibraryCandidate(self, records)


class LibraryCandidate:
    def __init__(self, library, records):
        self.library = library
        self.state = copy.deepcopy(library.state)
        self.records, self.duplicates = _record_map(records)
        self.reconcile = records is not None
        self.issues = []

    def _issue(self, code, fit_id=None, **details):
        item = {'code': code, **details}
        if fit_id is not None:
            item['id'] = fit_id
        if item not in self.issues:
            self.issues.append(item)

    def _active(self, fit_id, entry):
        if not self.reconcile:
            return True
        if fit_id in self.duplicates:
            self._issue('library_duplicate_id_disabled', fit_id)
            return False
        record = self.records.get(fit_id)
        if record is None:
            self._issue('library_source_missing_disabled', fit_id)
            return False
        if entry['sourceFingerprint'] != source_fingerprint(record):
            self._issue('library_source_changed_requires_preparation', fit_id)
            return False
        return True

    def _copy_texture(self, spec, source_root=None):
        row = copy.deepcopy(spec)
        source = Path(row['sourcePng'])
        if not source.is_absolute() and source_root:
            source = Path(source_root) / source
        if not source.is_file():
            raise ValueError('Missing prepared PNG: ' + str(source))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        destination = self.library.root / 'blobs' / (digest + '.png')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file():
            temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                shutil.copyfile(source, temporary)
                os.replace(temporary, destination)
            finally:
                if temporary.is_file():
                    temporary.unlink()
        elif hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise ValueError('Prepared library PNG failed its content hash: ' + str(destination))
        row['sourcePng'] = str(destination)
        row['sourceSha256'] = digest
        return row

    @staticmethod
    def _spec(row):
        spec = copy.deepcopy(row)
        for key in ('packagePath', 'objectPath', 'cookedObjectPath', 'compression', 'srgb',
                    'mipGenSettings', 'compressionNoAlpha'):
            spec.pop(key, None)
        path = _asset_path(row.get('assetPath') or row.get('objectPath') or row.get('cookedObjectPath'))
        if not path:
            raise ValueError('Library assets must use the prepared namespace')
        spec['assetPath'] = path
        spec.setdefault('assetName', path.rsplit('.', 1)[-1])
        return spec

    @staticmethod
    def _identity(asset):
        spec = copy.deepcopy(asset)
        if asset['kind'] == 'texture':
            spec['spec'].pop('sourcePng', None)
        return _digest(spec)

    def import_specs(self, prepared_manifest, cook_job, records=None, provenance='prepared',
                     options=None, source_root=None, replace=True, keep_previous=False):
        """Import a successful job or decoded installed snapshot into this candidate.

        Omitted/failed outfit entries keep their old result.  A partial incoming
        variant marked ``supported: false`` keeps its old working variant when
        the source definition is unchanged.  Exact PNGs are copied, never baked
        again.  Missing assets and conflicts reject that outfit, not the library.
        """
        if prepared_manifest.get('schemaVersion') != 1 or not isinstance(prepared_manifest.get('outfits'), dict):
            raise ValueError('Invalid prepared manifest')
        supplied, duplicates = _record_map(records) if records is not None else (self.records, self.duplicates)
        raw_assets = {}
        for kind, key in (('texture', 'textures'), ('material', 'materials')):
            for row in cook_job.get(key, []):
                spec = self._spec(row)
                path = spec['assetPath']
                candidate = {'kind': kind, 'spec': spec}
                if path in raw_assets and raw_assets[path] != candidate:
                    raise ValueError('Conflicting duplicate asset definitions: ' + path)
                raw_assets[path] = candidate
        imported = []
        for fit_id, incoming in prepared_manifest['outfits'].items():
            if fit_id in duplicates:
                self._issue('library_import_duplicate_id_rejected', fit_id)
                continue
            record = supplied.get(fit_id)
            if record is None:
                self._issue('library_import_source_missing', fit_id)
                continue
            old = self.state['outfits'].get(fit_id)
            if not replace and fit_id in self.state.get('removedOutfits', []):
                continue
            fingerprint = source_fingerprint(record)
            # Legacy snapshots must never make a changed source appear current.
            # Only an explicit successful re-preparation may replace that entry.
            if old and not replace:
                continue
            try:
                count = len(record['variants'])
                if incoming.get('originalCount') != count or len(incoming.get('variants', [])) != count:
                    raise ValueError('Prepared/source variant count differs')
                merged = copy.deepcopy(incoming)
                variant_options = []
                any_success = False
                for index, variant in enumerate(merged['variants']):
                    if variant.get('mesh') != record['variants'][index]['Mesh']:
                        raise ValueError('Prepared/source mesh differs at variant ' + str(index))
                    previous = None
                    if old and old.get('sourceFingerprint') == fingerprint:
                        previous = old['prepared']['variants'][index]
                    if variant.get('supported', True):
                        any_success = True
                        variant_options.append(copy.deepcopy(options or {}))
                    elif previous and previous.get('supported', True):
                        merged['variants'][index] = copy.deepcopy(previous)
                        old_options = old.get('variantOptions', [])
                        variant_options.append(copy.deepcopy(old_options[index] if index < len(old_options) else old.get('options', {})))
                        self._issue('library_previous_variant_retained', fit_id, variant=index)
                        any_success = True
                    else:
                        variant_options.append(copy.deepcopy(options or {}))
                if not any_success:
                    self._issue('library_no_success_previous_retained', fit_id)
                    continue
                # Traverse only actually referenced generated assets, including
                # material -> texture dependencies and directly assigned textures.
                pending = list(_references(merged))
                required, additions = set(), {}
                while pending:
                    path = pending.pop()
                    if path in required:
                        continue
                    required.add(path)
                    raw = raw_assets.get(path)
                    existing = self.state['assets'].get(path)
                    if raw is None:
                        if existing is None:
                            raise ValueError('Missing cook source for prepared asset: ' + path)
                        asset = existing
                    else:
                        asset = copy.deepcopy(raw)
                        if asset['kind'] == 'texture':
                            asset['spec'] = self._copy_texture(asset['spec'], source_root)
                        if existing and self._identity(existing) != self._identity(asset):
                            raise ValueError('Prepared asset path has conflicting content: ' + path)
                        additions[path] = asset
                    if asset['kind'] == 'material':
                        pending.extend(_references(asset['spec'].get('textureParameters', [])))
                entry = {'sourceFingerprint': fingerprint, 'prepared': merged,
                         'assetPaths': sorted(required), 'options': copy.deepcopy(options or {}),
                         'variantOptions': variant_options, 'provenance': str(provenance),
                         'source': record.get('source', ''), 'name': record.get('name', fit_id)}
                if keep_previous and old and old.get('sourceFingerprint') == fingerprint:
                    history = copy.deepcopy(old.get('history', []))
                    previous = copy.deepcopy(old);previous.pop('history', None)
                    if previous['prepared'] != merged or previous.get('variantOptions') != variant_options:
                        history.append(previous)
                    history = [frame for frame in history if frame['prepared'] != merged or frame.get('variantOptions') != variant_options]
                    entry['history'] = history
                    entry['assetPaths'] = sorted(set(entry['assetPaths']).union(*(set(frame['assetPaths']) for frame in history)))
                self.state['assets'].update(additions)
                self.state['outfits'][fit_id] = entry
                if fit_id in self.state.get('removedOutfits', []):
                    self.state['removedOutfits'].remove(fit_id)
                imported.append(fit_id)
            except (KeyError, ValueError, TypeError, OSError) as error:
                self._issue('library_import_failed_previous_retained', fit_id, detail=str(error))
        return imported

    def import_legacy(self, output):
        """Migrate a pre-library output without changing it or installed files."""
        output = Path(output)
        # Install is the last delivery that successfully staged.  A failed old
        # job may have overwritten root Prepared.json before its cook failed.
        manifests = [output / 'Install/SB/Binaries/Win64/ue4ss/Mods/DekCNS/Scripts/OutfitReversal/Prepared.json', output / 'Prepared.json']
        prepared_path = next((path for path in manifests if path.is_file()), None)
        job_paths = [output / 'cooked/prepared-cook-manifest.json', output / 'cook-job.json']
        job_path = next((path for path in job_paths if path.is_file()), None)
        if not prepared_path:
            return []
        if not job_path:
            self._issue('library_legacy_assets_need_recovery', source=str(prepared_path))
            return []
        return self.import_specs(_read(prepared_path), _read(job_path), provenance='legacy-output:' + str(output),
                                 source_root=output, replace=False)

    def active_entries(self):
        return {fit_id: entry for fit_id, entry in self.state['outfits'].items() if self._active(fit_id, entry)}

    def remove(self, ids):
        """Forget selected colour variants and block their legacy re-import."""
        removed = set(self.state.get('removedOutfits', []))
        for fit_id in ids:
            self.state['outfits'].pop(fit_id, None)
            removed.add(fit_id)
        self.state['removedOutfits'] = sorted(removed)

    def prepared_manifest(self):
        return {'schemaVersion': 1, 'libraryRevision': self.state.get('revision', 0) + 1,
                'outfits': {fit_id: prepared_value(entry)
                            for fit_id, entry in sorted(self.active_entries().items(), key=lambda item: item[0].casefold())}}

    def cook_job(self, template):
        job = copy.deepcopy(template)
        required = set()
        for entry in self.active_entries().values():
            required.update(entry['assetPaths'])
        job['textures'], job['materials'] = [], []
        for path in sorted(required):
            asset = self.state['assets'][path]
            row = copy.deepcopy(asset['spec'])
            if asset['kind'] == 'texture':
                png = Path(row['sourcePng'])
                if not png.is_file() or hashlib.sha256(png.read_bytes()).hexdigest() != row['sourceSha256']:
                    raise ValueError('Library texture missing or modified; rebuild before replacing installed output: ' + str(png))
            job['textures' if asset['kind'] == 'texture' else 'materials'].append(row)
        return job

    def commit(self):
        """Commit after cooking and successful delivery promotion, never before."""
        library = self.library
        actual = _read(library.index) if library.index.is_file() else {
            'schemaVersion': SCHEMA, 'revision': 0, 'outfits': {}, 'assets': {}}
        if _digest(actual) != library._base_digest:
            raise ValueError('Prepared library changed during this run; rerun without concurrent preparers.')
        self.state['revision'] = actual.get('revision', 0) + 1
        library.root.mkdir(parents=True, exist_ok=True)
        temporary = library.index.with_name('index.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(self.state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            os.replace(temporary, library.index)
        finally:
            if temporary.is_file():
                temporary.unlink()
        library.state = copy.deepcopy(self.state)
        library._base_digest = _digest(library.state)
        return library.index
