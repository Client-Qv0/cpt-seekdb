FROM ubuntu:24.04 AS builder
RUN apt-get update && apt-get install -y --no-install-recommends g++ cmake make \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY CMakeLists.txt ./
COPY src/ src/
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --parallel 2

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /src/build/minivectordb /app/minivectordb
VOLUME ["/data"]
ENTRYPOINT ["/app/minivectordb"]
# Default interface: official stdin/stdout JSONL protocol.
CMD ["--data-dir", "/data"]
