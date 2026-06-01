FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY . .
RUN go mod download && go build -o /azure-tickets .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /azure-tickets /usr/local/bin/azure-tickets
ENV LISTEN=":8082"
ENV CLOUDLEARN_ENDPOINT="http://host.docker.internal:9000"
EXPOSE 8082
ENTRYPOINT ["/usr/local/bin/azure-tickets"]
