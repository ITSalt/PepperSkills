FROM golang:1.26-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=1 go build -trimpath -ldflags='-s -w' -o /gateway .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates nftables util-linux curl && rm -rf /var/lib/apt/lists/* && mkdir /data && chown 10001:10001 /data
COPY --from=build /gateway /usr/local/bin/gateway
COPY entrypoint.sh /usr/local/bin/entrypoint
COPY firewall.nft /etc/gateway-firewall.nft
RUN chmod 755 /usr/local/bin/entrypoint
EXPOSE 8443 8080
VOLUME /data
ENTRYPOINT ["/usr/local/bin/entrypoint"]
CMD ["/usr/local/bin/gateway"]
