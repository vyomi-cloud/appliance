# Multi-stage build for java-orders. Build with:
#   docker build -t java-orders:latest .
# Run with (point ENDPOINT at the simulator on host):
#   docker run --rm --network host \
#     -e AWS_ENDPOINT_URL=http://192.168.252.7:9000 \
#     -e SECRET_NAME=prod/orders/db \
#     -e BUCKET=orders-receipts \
#     -p 8080:8080 \
#     java-orders:latest
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /app
COPY pom.xml .
RUN mvn -B dependency:go-offline
COPY src ./src
# Skip test compilation entirely in the production build — the API-pass test
# (src/test/.../ApiPassTest.java) is run separately via `mvn test` against a
# running simulator.
RUN mvn -B package -Dmaven.test.skip=true

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /app/target/java-orders-1.0.0.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
