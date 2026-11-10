            List of relations
 Schema |     Name     | Type  |  Owner  
--------+--------------+-------+---------
 public | models       | table | conduit
 public | reservations | table | conduit
 public | teams        | table | conduit


                            Table "public.models"
        Column         |       Type       | Collation | Nullable | Default 
-----------------------+------------------+-----------+----------+---------
 name                  | text             |           | not null | 
 provider              | text             |           | not null | 
 cost_per_input_token  | double precision |           | not null | 0.0
 cost_per_output_token | double precision |           | not null | 0.0
Indexes:
    "models_pkey" PRIMARY KEY, btree (name)


                            Table "public.teams"
     Column     |       Type       | Collation | Nullable |     Default     
----------------+------------------+-----------+----------+-----------------
 api_key        | text             |           | not null | 
 team_id        | text             |           | not null | 
 team_name      | text             |           | not null | 
 allowed_models | text[]           |           | not null | 
 rate_limit     | integer          |           | not null | 
 budget_limit   | double precision |           | not null | 
 budget_period  | text             |           | not null | 'monthly'::text
 current_spend  | numeric(10,2)    |           |          | 0.00
Indexes:
    "teams_pkey" PRIMARY KEY, btree (api_key)
Referenced by:
    TABLE "reservations" CONSTRAINT "reservations_api_key_fkey" FOREIGN KEY (api_key) REFERENCES teams(api_key)


                               Table "public.reservations"
     Column      |            Type             | Collation | Nullable |      Default      
-----------------+-----------------------------+-----------+----------+-------------------
 id              | uuid                        |           | not null | gen_random_uuid()
 api_key         | text                        |           |          | 
 reserved_amount | numeric(10,8)               |           |          | 
 reserved_at     | timestamp without time zone |           |          | now()
Indexes:
    "reservations_pkey" PRIMARY KEY, btree (id)
Foreign-key constraints:
    "reservations_api_key_fkey" FOREIGN KEY (api_key) REFERENCES teams(api_key)



