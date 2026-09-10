"""Recompute `line.news.is_published` from `state`.

`is_published` started life as a plain Boolean the user could tick, and was
later changed to a stored compute of `state == 'published'`. There was no
migration, so on any tenant that predates the change the stored column still
holds whatever was ticked back then — decoupled from state.

On markstudio that meant two `state='draft'` articles with `is_published=True`
were served to anyone who asked, with no login: the list endpoint, the article
view and the cover-image endpoint all keyed off the stale column.

The controllers now read `state` directly, but the column is still used by the
ACL/record-rule path, so it has to be brought back in line.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        UPDATE line_news
           SET is_published = (state = 'published')
         WHERE is_published IS DISTINCT FROM (state = 'published')
    """)
    fixed = cr.rowcount
    if fixed:
        _logger.warning(
            'line.news: realigned is_published with state on %d row(s) — '
            'these were readable (or hidden) against their actual state',
            fixed)
