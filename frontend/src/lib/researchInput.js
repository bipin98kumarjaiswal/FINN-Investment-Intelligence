// Pure client-side input guard: company search and question entry have distinct purposes.
export function isLikelyResearchQuestion(value) {
  const input = String(value || '').trim()
  if (!input) return false
  if (input.length > 60 || input.includes('?')) return true
  if (/^(what|why|how|when|where|which|explain|compare|analy[sz]e|tell me|can you|could you|does|did|is it|are there)\b/i.test(input)) return true
  if (input.split(/\s+/).length > 7) return true
  return false
}

export function companySearchHint(value) {
  return isLikelyResearchQuestion(value)
    ? 'This looks like a research question. First select an NSE company above; then enter your full question in Step 2, “Ask FINN”.'
    : ''
}
