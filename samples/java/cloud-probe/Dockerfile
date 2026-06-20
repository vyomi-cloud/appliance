# cloud-probe — multi-stage build so it runs on any Vyomi VM with just docker
# (the JVM ships inside the runtime image; nothing is needed on the host).
#
#   docker build -t cloud-probe:local .
#   docker run --rm -p 8080:8080 -e CLOUDPROBE_ENDPOINT=http://<appliance>:9000 cloud-probe:local
#   curl localhost:8080/probe/aws | jq

# ── build ────────────────────────────────────────────────────────────────
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /app
COPY pom.xml .
# Warm the dependency cache so source-only changes rebuild fast.
RUN mvn -q -B dependency:go-offline 2>/dev/null || true
COPY src ./src
RUN mvn -q -B -DskipTests package

# ── runtime ──────────────────────────────────────────────────────────────
FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /app/target/cloud-probe.jar app.jar
EXPOSE 8080
# CLOUDPROBE_ENDPOINT is injected at `docker run` time (the appliance address
# the VM can reach, e.g. http://10.6.16.1:9000).
# Firestore is a SEPARATE container: the probe defaults FIRESTORE_EMULATOR_HOST
# to the service name cloudlearn-firestore:8080 (works co-located on the
# appliance docker network). Under `--network host`, override it with the
# published port, e.g. -e FIRESTORE_EMULATOR_HOST=127.0.0.1:8080.
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
