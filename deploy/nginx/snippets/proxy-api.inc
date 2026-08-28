# Cabeceras del proxy hacia la API. Se incluye desde cada `location` en vez de
# repetirlas: una sola definición es una sola cosa que revisar.
#
# X-Real-IP es la que el backend usa para el rate limiting por IP y para dejar
# constancia en la bitácora (app/api/deps.py, client_ip). Si nginx no la pusiera,
# todos los intentos de login llegarían con la IP del propio contenedor y el
# bloqueo por IP protegería a todo el mundo por igual, es decir, a nadie.
proxy_pass http://api:8000;
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_connect_timeout 5s;
proxy_send_timeout 60s;
proxy_read_timeout 60s;
# Sin buffering en las descargas de XML y RIDE: son ficheros y el cliente los
# recibe a medida que salen.
proxy_buffering on;
proxy_request_buffering on;
