# go-inventory multi-stage build.
#   docker build -t go-inventory:latest .
#   docker run --rm --network host \
#     -e GCP_ENDPOINT_URL=http://192.168.252.7:9000 \
#     -e PUBSUB_EMULATOR_HOST=192.168.252.7:8085 \
#     -p 8081:8081 \
#     go-inventory:latest
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download || true
COPY . .
RUN CGO_ENABLED=0 go build -o /out/inventory ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
WORKDIR /app
COPY --from=build /out/inventory /app/inventory
EXPOSE 8081
ENTRYPOINT ["/app/inventory"]
