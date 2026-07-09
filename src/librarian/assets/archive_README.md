# _archive/ — retired docs

Move a whole doc here (set its frontmatter `status: archived` first) when it's obsolete or superseded —
not just one wrong line. `librarian index` skips `_archive/`, so archived docs drop out of the catalog
but stay in the repo's history for reference.

Use this for **doc-level** retirement. For a single false-but-the-doc-is-otherwise-current line, don't
archive — quarantine the line in place with a `<!-- librarian:disputed: ... -->` marker instead (see the
Knowledge protocol).
