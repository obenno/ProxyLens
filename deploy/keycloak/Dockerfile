FROM quay.io/keycloak/keycloak:26.8.1@sha256:a78d6b79572168cb25886b80a8b5b8d4ed4390743e3eecb810538683e209dd6b AS upstream
FROM docker.io/library/eclipse-temurin:21-jdk@sha256:23cc5734ff46e776f51ce66eb9ee08444fd47caabec0a95b7eb6e94be2d3696d AS compiler
COPY --from=upstream /opt/keycloak/lib/lib/main/ /keycloak-lib/
COPY mapper /mapper
RUN mkdir -p /classes && javac --release 21 -cp '/keycloak-lib/*' -d /classes /mapper/src/io/proxylens/keycloak/FlatGroupIdsMapper.java \
    && cp -r /mapper/resources/* /classes/ \
    && jar --create --file /proxylens-group-ids.jar -C /classes .

FROM upstream AS builder
COPY --from=compiler --chown=keycloak:keycloak /proxylens-group-ids.jar /opt/keycloak/providers/proxylens-group-ids.jar
# Bound archive-builder threads on high-core hosts with low file-descriptor limits.
RUN JAVA_OPTS_APPEND=-XX:ActiveProcessorCount=2 /opt/keycloak/bin/kc.sh build --db=postgres --health-enabled=true --metrics-enabled=true

FROM upstream
COPY --from=builder /opt/keycloak/ /opt/keycloak/
