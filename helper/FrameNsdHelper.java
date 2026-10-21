package local.frame.nsd;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;

public final class FrameNsdHelper {
    private static Object service;
    private static Object context;
    private static PrintStream output;

    private static void initializeOutput() throws Exception {
        output =
            new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(output);
        System.setErr(
            new PrintStream(new FileOutputStream(FileDescriptor.err), true, "UTF-8"));
    }

    private static void log(String text) {
        System.out.println("FrameNsdHelper: " + text);
        System.out.flush();
    }

    private static Object call(Class<?> type, Object receiver, String name,
                               Class<?>[] parameterTypes, Object... args)
        throws Exception {
        Method method = type.getDeclaredMethod(name, parameterTypes);
        method.setAccessible(true);
        return method.invoke(receiver, args);
    }

    private static void allowHiddenApis() throws Exception {
        Class<?> vm = Class.forName("dalvik.system.VMRuntime");
        Object runtime = call(vm, null, "getRuntime", new Class<?>[0]);
        call(vm, runtime, "setHiddenApiExemptions", new Class<?>[] {String[].class},
             (Object) new String[] {"L"});
    }

    private static Object makeContext() throws Exception {
        Class<?> looper = Class.forName("android.os.Looper");
        if (call(looper, null, "getMainLooper", new Class<?>[0]) == null) {
            call(looper, null, "prepareMainLooper", new Class<?>[0]);
        }
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = call(activityThread, null, "systemMain", new Class<?>[0]);
        return call(activityThread, thread, "getSystemContext", new Class<?>[0]);
    }

    private static Object existingService() throws Exception {
        return call(Class.forName("android.os.ServiceManager"), null, "checkService",
                    new Class<?>[] {String.class}, "servicediscovery");
    }

    private static Object makeService(Class<?> nsd) throws Exception {
        final Class<?> settingsType =
            Class.forName("com.android.server.NsdService$NsdSettings");
        Object settings = Proxy.newProxyInstance(
            settingsType.getClassLoader(), new Class<?>[] {settingsType},
            new InvocationHandler() {
                public Object invoke(Object proxy, Method method, Object[] args) {
                    if (method.getName().equals("isEnabled"))
                        return true;
                    if (method.getName().equals("toString"))
                        return "FrameTemporaryNsdSettings";
                    if (method.getName().equals("hashCode"))
                        return System.identityHashCode(proxy);
                    if (method.getName().equals("equals"))
                        return proxy == args[0];
                    return null;
                }
            });
        final Class<?> supplierType =
            Class.forName("com.android.server.NsdService$DaemonConnectionSupplier");
        Object supplier = Proxy.newProxyInstance(
            supplierType.getClassLoader(), new Class<?>[] {supplierType},
            new InvocationHandler() {
                public Object invoke(Object proxy, Method method, Object[] args)
                    throws Throwable {
                    if (method.getName().equals("get")) {
                        Class<?> daemon = Class.forName(
                            "com.android.server.NsdService$DaemonConnection");
                        Class<?> callback = Class.forName(
                            "com.android.server.NsdService$NativeCallbackReceiver");
                        Constructor<?> constructor =
                            daemon.getDeclaredConstructor(callback);
                        constructor.setAccessible(true);
                        return constructor.newInstance(args[0]);
                    }
                    if (method.getName().equals("toString"))
                        return "FrameNsdDaemonSupplier";
                    if (method.getName().equals("hashCode"))
                        return System.identityHashCode(proxy);
                    if (method.getName().equals("equals"))
                        return proxy == args[0];
                    return null;
                }
            });
        Class<?> threadType = Class.forName("android.os.HandlerThread");
        Object thread =
            threadType.getConstructor(String.class).newInstance("FrameNsdService");
        threadType.getMethod("start").invoke(thread);
        Class<?> looperType = Class.forName("android.os.Looper");
        Object looper = threadType.getMethod("getLooper").invoke(thread);
        Class<?> handlerType = Class.forName("android.os.Handler");
        Object handler = handlerType.getConstructor(looperType).newInstance(looper);
        Constructor<?> constructor =
            nsd.getDeclaredConstructor(Class.forName("android.content.Context"),
                                       settingsType, handlerType, supplierType);
        constructor.setAccessible(true);
        return constructor.newInstance(context, settings, handler, supplier);
    }

    private static void serve() throws Exception {
        if (existingService() != null) {
            log("Service already exists; refusing to replace it.");
            System.exit(2);
        }
        context = makeContext();
        log("Creating existing Android NsdService; waiting for its mdns daemon.");
        Class<?> nsd = Class.forName("com.android.server.NsdService");
        service = makeService(nsd);
        Field callbackField = nsd.getDeclaredField("mDaemonCallback");
        callbackField.setAccessible(true);
        Object callback = callbackField.get(service);
        call(callback.getClass(), callback, "awaitConnection", new Class<?>[0]);
        Class<?> binder = Class.forName("android.os.IBinder");
        call(Class.forName("android.os.ServiceManager"), null, "addService",
             new Class<?>[] {String.class, binder}, "servicediscovery", service);
        if (existingService() == null) {
            throw new IllegalStateException(
                "Service registration did not become visible.");
        }
        log("READY: servicediscovery registered.");
        call(Class.forName("android.os.Looper"), null, "loop", new Class<?>[0]);
    }

    public static void main(String[] args) {
        try {
            initializeOutput();
            log("Starting Java main");
            allowHiddenApis();
            serve();
        } catch (Throwable error) {
            while (error instanceof InvocationTargetException &&
                   error.getCause() != null) {
                error = error.getCause();
            }
            error.printStackTrace(System.err);
            System.exit(1);
        }
    }
}
