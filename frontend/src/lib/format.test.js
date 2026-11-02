import test from 'node:test'
import assert from 'node:assert/strict'
import { indianMoney, scoreSort, safeHttpUrl, customWindowParams, pdfStatusInfo } from './format.js'
import { briefingPath } from './api.js'

test('correctly displays missing market values instead of zero', () => {
  assert.equal(indianMoney(null), '—')
  assert.equal(indianMoney(1573.5), '₹1,573.50')
})
test('sorts by actual priority score before event time', () => {
  const items = scoreSort([
    { score: 40, published_at_utc: '2026-11-01T12:00:00Z' },
    { score: 80, published_at_utc: '2026-10-31T12:00:00Z' },
  ])
  assert.equal(items[0].score, 80)
})
test('rejects script URLs and permits normal original source links', () => {
  assert.equal(safeHttpUrl('javascript:alert(1)'), null)
  assert.equal(safeHttpUrl('https://nsearchives.nseindia.com/example.pdf'), 'https://nsearchives.nseindia.com/example.pdf')
})
test('rejects invalid custom windows and serializes valid ones', () => {
  assert.throws(() => customWindowParams('2026-10-20T16:00', '2026-10-19T16:00'))
  const range = customWindowParams('2026-10-20T16:00', '2026-10-21T16:00')
  assert.ok(range.start.endsWith('Z'))
  assert.ok(range.end.endsWith('Z'))
})
test('correctly requests windowed and expanded filing digest', () => {
  assert.equal(briefingPath({ mode: 'day' }), '/briefing?hours=24')
  assert.equal(briefingPath({ mode: 'week', includeRoutine: true }), '/briefing?hours=168&include_routine=true')
  assert.equal(new URLSearchParams(briefingPath({ mode: 'custom', from: '2026-10-01T00:00:00Z', until: '2026-10-02T00:00:00Z' }).split('?')[1]).get('start'), '2026-10-01T00:00:00Z')
})
test('shows skipped PDF state accurately', () => {
  assert.match(pdfStatusInfo('skipped_too_large').text, /too large/)
  assert.notEqual(pdfStatusInfo('skipped_too_large').text, 'PDF examined')
})
