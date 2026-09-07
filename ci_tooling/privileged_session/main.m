// Private, short-lived Authorization Services child. Never install setuid.
// Its only command channel is the pipe inherited from the authenticating app.
#import <Foundation/Foundation.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <unistd.h>

static void reply(NSDictionary *value) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    fwrite(data.bytes, 1, data.length, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

static NSDictionary *execute(NSDictionary *request) {
    NSArray *argv = request[@"argv"];
    if (![argv isKindOfClass:NSArray.class] || !argv.count ||
        ![argv[0] isKindOfClass:NSString.class] || ![argv[0] hasPrefix:@"/"]) {
        return @{@"error": @"Expected an absolute executable path"};
    }
    for (id arg in argv) {
        if (![arg isKindOfClass:NSString.class]) return @{@"error": @"Invalid argument"};
    }
    NSTask *task = [NSTask new];
    task.executableURL = [NSURL fileURLWithPath:argv[0]];
    task.arguments = [argv subarrayWithRange:NSMakeRange(1, argv.count - 1)];
    task.environment = @{@"PATH": @"/usr/bin:/bin:/usr/sbin:/sbin", @"HOME": @"/var/root",
                         @"USER": @"root", @"LOGNAME": @"root", @"TMPDIR": @"/private/tmp"};
    task.currentDirectoryURL = [NSURL fileURLWithPath:request[@"cwd"] ?: @"/"];
    NSPipe *out = [NSPipe pipe], *err = [NSPipe pipe], *input = [NSPipe pipe];
    task.standardOutput = out;
    task.standardError = [request[@"merge_stderr"] boolValue] ? out : err;
    task.standardInput = input;
    NSError *error = nil;
    if (![task launchAndReturnError:&error]) return @{@"error": error.localizedDescription};
    NSMutableData *stdoutData = [NSMutableData data], *stderrData = [NSMutableData data];
    NSData *inputData = [[NSData alloc] initWithBase64EncodedString:request[@"input"] ?: @"" options:0];
    int outFD = out.fileHandleForReading.fileDescriptor;
    int errFD = err.fileHandleForReading.fileDescriptor;
    int inFD = input.fileHandleForWriting.fileDescriptor;
    for (NSNumber *fd in @[@(outFD), @(errFD), @(inFD)]) {
        fcntl(fd.intValue, F_SETFL, fcntl(fd.intValue, F_GETFL) | O_NONBLOCK);
    }
    BOOL outDone = NO, errDone = [request[@"merge_stderr"] boolValue], inDone = NO;
    NSUInteger inputOffset = 0;
    double timeout = [request[@"timeout"] doubleValue];
    double deadline = NSProcessInfo.processInfo.systemUptime + timeout;
    double drainDeadline = 0;
    BOOL timedOut = NO;
    while (task.running || !outDone || !errDone) {
        double now = NSProcessInfo.processInfo.systemUptime;
        if (task.running && timeout > 0 && now >= deadline && !timedOut) {
            timedOut = YES;
            kill(task.processIdentifier, SIGKILL);
        }
        if (!task.running && !drainDeadline) drainDeadline = now + 2;
        // A grandchild must not keep this private session blocked forever by
        // retaining its parent's output descriptors after that parent exits.
        if (drainDeadline && now >= drainDeadline) break;
        if (!inDone) {
            ssize_t written = write(inFD, (const char *)inputData.bytes + inputOffset, inputData.length - inputOffset);
            if (written > 0) inputOffset += written;
            if (inputOffset == inputData.length || (written < 0 && errno != EAGAIN && errno != EINTR)) {
                [input.fileHandleForWriting closeFile];
                inDone = YES;
            }
        }
        for (NSUInteger index = 0; index < 2; index++) {
            BOOL *done = index == 0 ? &outDone : &errDone;
            if (*done) continue;
            NSMutableData *destination = index == 0 ? stdoutData : stderrData;
            char buffer[65536];
            ssize_t count = read(index == 0 ? outFD : errFD, buffer, sizeof(buffer));
            if (count > 0) [destination appendBytes:buffer length:count];
            else if (count == 0 || (errno != EAGAIN && errno != EINTR)) *done = YES;
        }
        usleep(1000);
    }
    [task waitUntilExit];
    if (!inDone) [input.fileHandleForWriting closeFile];
    [out.fileHandleForReading closeFile];
    [err.fileHandleForReading closeFile];
    int status = task.terminationStatus;
    if (task.terminationReason == NSTaskTerminationReasonUncaughtSignal) status = -status;
    return @{@"returncode": @(status), @"timed_out": @(timedOut),
             @"stdout": [stdoutData base64EncodedStringWithOptions:0],
             @"stderr": [stderrData base64EncodedStringWithOptions:0]};
}

static BOOL trustedExecutable(void) {
    const char *expected = "/Library/Application Support/Dortania/OpenCore-Patcher.app/Contents/MacOS/oclp-privileged-session";
    char executable[PATH_MAX], resolved[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0 || !realpath(executable, resolved) ||
        strcmp(resolved, expected) != 0) return NO;
    NSString *path = @(expected);
    while (YES) {
        struct stat info;
        if (lstat(path.fileSystemRepresentation, &info) != 0 || S_ISLNK(info.st_mode) ||
            info.st_uid != 0 || (info.st_mode & 0022)) return NO;
        if ([path isEqualToString:@"/"]) return YES;
        path = path.stringByDeletingLastPathComponent;
    }
}

int main(int argc, const char *argv[] __attribute__((unused))) {
    @autoreleasepool {
        struct stat input;
        if (argc != 1 || geteuid() != 0 || !trustedExecutable() || fstat(STDIN_FILENO, &input) != 0 ||
            (!S_ISFIFO(input.st_mode) && !S_ISSOCK(input.st_mode)) || setuid(0) != 0) return 77;
        // Prevent children from inheriting the authorization channel.
        fcntl(STDIN_FILENO, F_SETFD, FD_CLOEXEC);
        fcntl(STDOUT_FILENO, F_SETFD, FD_CLOEXEC);
        signal(SIGPIPE, SIG_IGN);
        reply(@{@"protocol": @1, @"uid": @(geteuid())});
        char *line = NULL;
        size_t capacity = 0;
        ssize_t length;
        while ((length = getline(&line, &capacity, stdin)) > 0) {
            @autoreleasepool {
                NSData *data = [NSData dataWithBytes:line length:length];
                id request = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
                if (![request isKindOfClass:NSDictionary.class]) break;
                @try { reply(execute(request)); }
                @catch (NSException *exception) { reply(@{@"error": exception.reason ?: @"Worker error"}); }
            }
        }
        free(line);
    }
    return 0;
}
