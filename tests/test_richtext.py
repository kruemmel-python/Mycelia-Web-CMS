from __future__ import annotations

import json
import pytest

from cms.richtext import RichTextError, canonical_json, normalize_document, plain_text, validate_richtext


def test_plaintext_migrates_without_interpreting_html():
    value = '<script>alert(1)</script>\n\n<strong>nicht HTML</strong>'
    encoded = validate_richtext(value, 'document', max_chars=10000, required=True)
    doc = json.loads(encoded)
    assert doc['schema'] == 'MYCELIA_RICHTEXT'
    assert plain_text(encoded) == value
    assert doc['blocks'][0]['runs'][0]['text'].startswith('<script>')


def test_rejects_unknown_blocks_and_javascript_links():
    bad_block = {'schema':'MYCELIA_RICHTEXT','version':1,'profile':'document','blocks':[{'type':'iframe','runs':[]}]}
    with pytest.raises(RichTextError):
        canonical_json(bad_block, 'document')
    bad_link = {'schema':'MYCELIA_RICHTEXT','version':1,'profile':'document','blocks':[{'type':'paragraph','runs':[{'text':'x','marks':[],'link':'javascript:alert(1)'}]}]}
    with pytest.raises(RichTextError):
        canonical_json(bad_link, 'document')


def test_profile_is_server_authoritative():
    table = {'schema':'MYCELIA_RICHTEXT','version':1,'profile':'document','blocks':[{'type':'table','rows':[[[{'text':'x','marks':[]}]]]}]}
    with pytest.raises(RichTextError):
        canonical_json(table, 'compact')


def test_fixed_tone_size_alignment_are_allowlisted():
    doc = {
        'schema':'MYCELIA_RICHTEXT','version':1,'profile':'standard',
        'blocks':[{'type':'paragraph','align':'center','runs':[{'text':'Hallo','marks':['bold'],'tone':'accent','size':'large'}]}]
    }
    clean = normalize_document(doc, 'standard')
    run = clean['blocks'][0]['runs'][0]
    assert clean['blocks'][0]['align'] == 'center'
    assert run['tone'] == 'accent' and run['size'] == 'large'
    bad = json.loads(json.dumps(doc)); bad['blocks'][0]['runs'][0]['tone'] = 'expression(alert(1))'
    with pytest.raises(RichTextError):
        normalize_document(bad, 'standard')


def test_https_and_internal_links_only():
    good = {'schema':'MYCELIA_RICHTEXT','version':1,'profile':'document','blocks':[{'type':'paragraph','runs':[{'text':'intern','marks':[],'link':'/s/shop'}]},{'type':'button_link','text':'Extern','href':'https://example.test/path'}]}
    assert json.loads(canonical_json(good, 'document'))['blocks'][1]['href'].startswith('https://')
    bad = json.loads(json.dumps(good)); bad['blocks'][1]['href'] = '//evil.test/x'
    with pytest.raises(RichTextError):
        canonical_json(bad, 'document')

def test_jinja_renderer_escapes_text_without_safe_filter():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader
    root = Path(__file__).resolve().parents[1] / 'templates'
    env = Environment(loader=FileSystemLoader(str(root)), autoescape=True)
    template = env.from_string("{% from 'richtext/view.html' import render_richtext %}{{ render_richtext(doc) }}")
    doc = normalize_document('<script>alert(1)</script>', 'document')
    rendered = template.render(doc=doc)
    assert '<script>' not in rendered
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in rendered
