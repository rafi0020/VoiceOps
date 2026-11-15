FROM alpine:3.22
RUN apk add --no-cache pgbouncer
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
RUN adduser -D -H pgb
USER pgb
EXPOSE 6432
ENTRYPOINT ["/entrypoint.sh"]
