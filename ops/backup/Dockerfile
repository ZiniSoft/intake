# pg_dump must match the server's major version, so this image starts from the database image.
FROM postgres:16-alpine
RUN apk add --no-cache python3 py3-boto3 openssl tar tzdata
COPY backup.py restore.py /opt/
ENTRYPOINT []
CMD ["python3", "/opt/backup.py"]
