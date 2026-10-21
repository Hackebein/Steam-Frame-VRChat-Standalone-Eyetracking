#include <arpa/inet.h>
#include <array>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <linux/futex.h>
#include <pthread.h>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <vector>

static volatile sig_atomic_t running = 1;
static void stop(int) { running = 0; }
static_assert(sizeof(pthread_mutex_t) <= 48, "Unexpected mutex ABI");
static constexpr float left_closed_threshold = .26f, left_open_threshold = .70f;
static constexpr float right_closed_threshold = .29f, right_open_threshold = .75f;

template <class T> static T read_value(const unsigned char *p, size_t offset) {
  T value;
  std::memcpy(&value, p + offset, sizeof value);
  return value;
}

static bool lock_metadata(unsigned char *p) {
  timespec deadline{};
  clock_gettime(CLOCK_REALTIME, &deadline);
  deadline.tv_nsec += 50000000;
  if (deadline.tv_nsec >= 1000000000) {
    ++deadline.tv_sec;
    deadline.tv_nsec -= 1000000000;
  }
  auto *mutex = reinterpret_cast<pthread_mutex_t *>(p + 8);
  int error = pthread_mutex_timedlock(mutex, &deadline);
  if (error == EOWNERDEAD) {
    error = pthread_mutex_consistent(mutex);
    if (error)
      pthread_mutex_unlock(mutex);
  }
  if (error == ETIMEDOUT)
    return false;
  if (error)
    throw std::runtime_error(std::string("Cannot lock eye-server metadata: ") +
                             std::strerror(error));
  return true;
}

static void append_string(std::vector<unsigned char> &out, const std::string &text) {
  out.insert(out.end(), text.begin(), text.end());
  out.push_back(0);
  while (out.size() % 4)
    out.push_back(0);
}

static void send_values(int socket, const std::string &address,
                        const std::vector<float> &values) {
  std::vector<unsigned char> packet;
  append_string(packet, address);
  append_string(packet, "," + std::string(values.size(), 'f'));
  for (float value : values) {
    uint32_t bits;
    std::memcpy(&bits, &value, 4);
    bits = htonl(bits);
    const auto *p = reinterpret_cast<const unsigned char *>(&bits);
    packet.insert(packet.end(), p, p + 4);
  }
  if (::send(socket, packet.data(), packet.size(), MSG_DONTWAIT) < 0 &&
      errno != EAGAIN && errno != ENOBUFS && errno != EINTR)
    throw std::runtime_error(std::string("OSC send failed: ") + std::strerror(errno));
}

int main() {
  try {
    int fd = open("/dev/shm/eye-server.mmap", O_RDWR | O_CLOEXEC);
    if (fd < 0)
      throw std::runtime_error("Cannot open eye-server shared memory");
    struct stat st{};
    if (fstat(fd, &st) || st.st_size < 64)
      throw std::runtime_error("Invalid shared-memory file");
    auto *p = static_cast<unsigned char *>(
        mmap(nullptr, st.st_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0));
    if (p == MAP_FAILED)
      throw std::runtime_error("Cannot map eye-server data");
    if (read_value<uint32_t>(p, 0) != 5 || static_cast<size_t>(st.st_size) < 0x4f21f ||
        read_value<uint32_t>(p, 4) != 1)
      throw std::runtime_error("Unsupported or uninitialized eye-server layout");
    sockaddr_in target{};
    target.sin_family = AF_INET;
    target.sin_port = htons(9000);
    target.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    int sock = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (sock < 0 || connect(sock, reinterpret_cast<sockaddr *>(&target), sizeof target))
      throw std::runtime_error("Cannot create local OSC socket");
    std::signal(SIGINT, stop);
    std::signal(SIGTERM, stop);
    std::cout << "READY: layout=5 target=127.0.0.1:9000" << std::endl;
    auto report = std::chrono::steady_clock::now();
    auto file_check = report;
    uint64_t sent = 0, total = 0, rejected = 0;
    while (running) {
      auto now = std::chrono::steady_clock::now();
      if (std::chrono::duration<double>(now - file_check).count() >= 2) {
        struct stat current{};
        if (stat("/dev/shm/eye-server.mmap", &current) || current.st_dev != st.st_dev ||
            current.st_ino != st.st_ino || current.st_size != st.st_size)
          throw std::runtime_error(
              "Eye-server data was recreated; restarting is required");
        file_check = now;
      }
      if (!lock_metadata(p)) {
        usleep(5000);
        continue;
      }
      auto *seq_ptr = reinterpret_cast<uint32_t *>(p + 0x38);
      uint32_t sequence = __atomic_load_n(seq_ptr, __ATOMIC_ACQUIRE);
      __atomic_store_n(reinterpret_cast<uint32_t *>(p + 0x3c), 1u, __ATOMIC_RELEASE);
      pthread_mutex_unlock(reinterpret_cast<pthread_mutex_t *>(p + 8));
      timespec timeout{0, 20000000};
      syscall(SYS_futex, seq_ptr, FUTEX_WAIT, sequence, &timeout, nullptr, 0);
      std::array<unsigned char, 0x81> record{};
      if (!lock_metadata(p)) {
        usleep(5000);
        continue;
      }
      bool fresh = __atomic_load_n(seq_ptr, __ATOMIC_ACQUIRE) != sequence;
      if (fresh)
        std::memcpy(record.data(), p + 0x157, record.size());
      pthread_mutex_unlock(reinterpret_cast<pthread_mutex_t *>(p + 8));
      if (fresh && read_value<uint32_t>(record.data(), 0) == 1) {
        std::vector<float> gaze;
        bool valid = true;
        for (int eye = 0; eye < 2; ++eye) {
          float x = read_value<float>(record.data(), 0x0d + 12 * eye);
          float y = read_value<float>(record.data(), 0x11 + 12 * eye);
          float z = -read_value<float>(record.data(), 0x15 + 12 * eye);
          float norm = std::sqrt(x * x + y * y + z * z);
          if (!std::isfinite(norm) || norm < 0.1f) {
            valid = false;
            break;
          }
          gaze.insert(gaze.end(), {x / norm, y / norm, z / norm});
        }
        float left = read_value<float>(record.data(), 0x79);
        float right = read_value<float>(record.data(), 0x7d);
        if (std::isfinite(left) && std::isfinite(right)) {
          auto clamp = [](float v) { return std::fmax(0.0f, std::fmin(1.0f, v)); };
          float closed =
              1.0f - (clamp((left - left_closed_threshold) /
                            (left_open_threshold - left_closed_threshold)) +
                      clamp((right - right_closed_threshold) /
                            (right_open_threshold - right_closed_threshold))) *
                         .5f;
          if (valid)
            send_values(sock, "/tracking/eye/LeftRightVec", gaze);
          send_values(sock, "/tracking/eye/EyesClosedAmount", {closed});
          ++sent;
          ++total;
        } else
          ++rejected;
      }
      if (std::chrono::duration<double>(now - report).count() >= 60) {
        std::cout << "updates=" << sent << " total=" << total
                  << " rejected=" << rejected << std::endl;
        report = now;
        sent = 0;
      }
    }
    std::cout << "STOPPED total=" << total << " rejected=" << rejected << std::endl;
    close(sock);
    munmap(p, st.st_size);
    close(fd);
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "frame-eyes: " << error.what() << std::endl;
    return 1;
  }
}
