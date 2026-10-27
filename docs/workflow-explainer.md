# One change and its history

This is a conceptual explanation of the implemented synthetic workflow. It does
not add an application run, measurement, deployment or security qualification.
The [design](DESIGN.md) and [installed operator walkthrough](operator-walkthrough.md)
remain the claim sources.

Creation gives the worked exception version 1. Assigning Sam produces version
2. A current operator requests Casey assignment with expected version 2.
The server checks session, role and organization, then commits the version-3
assignment, one history event and the response receipt together. An older
expected version refuses the business change.

A committed response can be lost. While the original intent is retained and
still authorized, an explicit retry uses its original key and body. A matching
receipt returns that version-3 response without another assignment event. A
separate refresh reads current state. Access and session checks remain
authoritative, and access recovery never automatically POSTs a business change.
Retiring a client intent cannot undo a transaction that already committed.

The record is resolved afterward at version 4. It has four events: creation,
Sam assignment, Casey assignment and resolution. The diagram's flow follows
the walkthrough's version-3 interrupted assignment and subsequent resolution;
it does not promise exactly-once effects for arbitrary external systems.

## Maintained source

The [model](workflow-explainer.json) contains the public labels, source revision
and pinned family roles. The [renderer](../tools/render_workflow_explainer.py)
writes wide and narrow Obscur PNG/SVG outputs with genuine supplied Inter faces.
Its SVG contains glyph outlines. Font binaries stay outside this repository.

Use an isolated authoring environment with
[the optional presentation requirements](../tools/requirements-presentation.txt).
Set `INTER_FONT_DIR` to the official static Inter TTF directory, then run:

```console
python tools/render_workflow_explainer.py
python tools/render_workflow_explainer.py --check
python tests/test_static_site.py
python tools/build_site.py
```

The renderer refuses missing or wrong font faces, missing label glyphs and text
outside its cards. The [rendering record](workflow-rendering.json) keeps source,
font and output identities. Rendering is separate from checking the actual
GitHub/profile placement and published static page.

## Static page boundary

The page builder admits only its named HTML, CSS, preference script, conceptual
exports, provenance and original dark capture. It does not import FastAPI,
connect to PostgreSQL, copy an environment or run fixture provisioning. The
ordinary application and its separately unfinished hosting route retain their
own setup and acceptance requirements.
