"""The same 16-company portfolio from FINN Phase 1."""
PORTFOLIO = [
    {"symbol":"RELIANCE","name":"Reliance Industries","sector":"Diversified"},
    {"symbol":"HDFCBANK","name":"HDFC Bank","sector":"Banking"},
    {"symbol":"ICICIBANK","name":"ICICI Bank","sector":"Banking"},
    {"symbol":"INFY","name":"Infosys","sector":"IT Services"},
    {"symbol":"TCS","name":"Tata Consultancy Services","sector":"IT Services"},
    {"symbol":"BHARTIARTL","name":"Bharti Airtel","sector":"Telecom"},
    {"symbol":"LT","name":"Larsen & Toubro","sector":"Engineering"},
    {"symbol":"TMPV","name":"Tata Motors Passenger Vehicles","sector":"Automobiles"},
    {"symbol":"SUNPHARMA","name":"Sun Pharmaceutical Industries","sector":"Pharmaceuticals"},
    {"symbol":"ITC","name":"ITC","sector":"FMCG"},
    {"symbol":"HINDUNILVR","name":"Hindustan Unilever","sector":"FMCG"},
    {"symbol":"TITAN","name":"Titan Company","sector":"Consumer"},
    {"symbol":"TATASTEEL","name":"Tata Steel","sector":"Metals"},
    {"symbol":"JSWENERGY","name":"JSW Energy","sector":"Power"},
    {"symbol":"TRENT","name":"Trent","sector":"Retail"},
    {"symbol":"DIXON","name":"Dixon Technologies","sector":"Electronics Manufacturing"},
]
BY_SYMBOL = {row["symbol"]: row for row in PORTFOLIO}
