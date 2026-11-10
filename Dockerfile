# The discarded certificate stage obtains signed Ubuntu GA packages, and
# verifies the resulting bundle before it can be used by the builder.
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852 AS certs
RUN rm -f /etc/apt/sources.list.d/ubuntu.sources \
    && printf '%s\n' 'deb http://archive.ubuntu.com/ubuntu noble main' > /etc/apt/sources.list \
    && apt-get update -o APT::Update::Error-Mode=any \
    && apt-get install -y --allow-downgrades --no-install-recommends ca-certificates=20240203 openssl=3.0.13-0ubuntu3 libssl3t64=3.0.13-0ubuntu3 \
    && printf '%s  %s\n' 6d84ab71cb726c0641b0af84303c316e3fa50db941dc8507d09045eb2fa5d238 /etc/ssl/certs/ca-certificates.crt | sha256sum -c -

FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852 AS builder
COPY --from=certs /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
RUN rm -f /etc/apt/sources.list.d/ubuntu.sources \
    && printf '%s\n' \
      'deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/20261109T000000Z noble main' \
      'deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/20261109T000000Z noble-updates main' \
      'deb [check-valid-until=no] https://snapshot.ubuntu.com/ubuntu/20261109T000000Z noble-security main' \
      > /etc/apt/sources.list \
    && apt-get update -o APT::Update::Error-Mode=any \
    && apt-get install -y --no-install-recommends g++=4:13.2.0-7ubuntu1 cmake=3.28.3-1build7 make=4.3-4.1build2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY CMakeLists.txt ./
COPY src/ src/
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --parallel 2

# The runtime is a fresh pinned base; no downgraded OpenSSL is copied into it.
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
RUN test "$(dpkg-query -W -f='${Version}' libstdc++6)" = '14.2.0-4ubuntu2~24.04.1'
COPY --from=builder /src/build/minivectordb /app/minivectordb
VOLUME ["/data"]
ENTRYPOINT ["/app/minivectordb"]
CMD ["--data-dir", "/data"]
