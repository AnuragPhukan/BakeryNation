This is a tiny local server you can run via 

docker compose up --build


Endpoints:

GET /job-types → ["cupcakes","cake","pastry_box"]

POST /estimate

request:

{
  "job_type": "cupcakes",
  "quantity": 24
}

response:

{
  "job_type": "cupcakes",
  "quantity": 24,
  "materials": [
    {"name":"flour","unit":"kg","qty":1.92},
    {"name":"sugar","unit":"kg","qty":1.44},
    {"name":"butter","unit":"kg","qty":0.96},
    {"name":"eggs","unit":"each","qty":12.0},
    {"name":"milk","unit":"L","qty":1.2},
    {"name":"vanilla","unit":"ml","qty":24.0},
    {"name":"baking_powder","unit":"kg","qty":0.024}
  ],
  "labor_hours": 1.2
}
