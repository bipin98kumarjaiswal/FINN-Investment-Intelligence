import test from 'node:test'
import assert from 'node:assert/strict'
import {isLikelyResearchQuestion,companySearchHint} from './researchInput.js'

test('company names and tickers remain valid company-search terms',()=>{
  assert.equal(isLikelyResearchQuestion('INFY'), false)
  assert.equal(isLikelyResearchQuestion('Tata Consultancy Services'),false)
})
test('long question is detected before FastAPI max-length validation',()=>{
  const q='What are the key business risks discussed in the Infosys annual report, especially cybersecurity?'
  assert.ok(q.length>60)
  assert.equal(isLikelyResearchQuestion(q),true)
  assert.match(companySearchHint(q),/First select an NSE company/)
})
test('short question also gets a helpful hint',()=>{
  assert.equal(isLikelyResearchQuestion('What are its risks?'),true)
})
