import tensorflow as tf
import hidden_marginalize
import json

class DRBM:
    def __init__(self, input_num, hidden_num, output_num, activation="continuous", dtype="float32", initial_sparse=10., random_bias=False):
        self.input_num = input_num
        self.hidden_num = hidden_num
        self.output_num = output_num
        self.dtype = dtype

        self.w1 = tf.Variable( tf.keras.initializers.GlorotUniform()((input_num, hidden_num), dtype=self.dtype), name="w1" )
        self.w2 = tf.Variable( tf.keras.initializers.GlorotUniform()((hidden_num, output_num), dtype=self.dtype), name="w2" )
        if random_bias:
            self.b1 = tf.Variable( tf.random.normal([hidden_num], dtype=self.dtype), name="b1" )
            self.b2 = tf.Variable( tf.random.normal([output_num], dtype=self.dtype), name="b2" )
        else:
            self.b1 = tf.Variable( tf.zeros((hidden_num), dtype=self.dtype), name="b1" )
            self.b2 = tf.Variable( tf.zeros((output_num), dtype=self.dtype), name="b2" )
        self.params = [self.b1, self.b2, self.w1, self.w2]

        self.enable_sparse = "sparse" in activation
        if self.enable_sparse:
            self.sparse = tf.Variable( tf.cast(tf.fill([hidden_num], initial_sparse), dtype=self.dtype), name="sparse" )
            self.params.append(self.sparse)
        self._marginalize = getattr(hidden_marginalize, activation).activation
        self.activation = activation

    # input: (N, i)
    # return (N, j, k)
    @tf.function
    def _signal_all(self, input):
        return tf.expand_dims(tf.matmul(input, self.w1) + self.b1, 2) + self.w2

    @tf.function
    def probability(self, input):
        sig = self._signal_all(input)
        if self.enable_sparse:
            act = self._marginalize(sig, self.sparse)
        else:
            act = self._marginalize(sig)
        energies = self.b2 + tf.reduce_sum(act, 1)
        return tf.nn.softmax(energies)

    @tf.function
    def _negative_log_likelihood(self, probs, labels):
        single_prob = tf.reduce_sum(probs * labels, 1)
        return -tf.reduce_mean(tf.math.log(single_prob))

    @tf.function
    def _kl_divergence(self, gen_drbm, sampling_size=1000):
        gen_data, gen_probs = gen_drbm.sampling(sampling_size)
        probs = self.probability(gen_data)
        kld = tf.reduce_mean( gen_probs * tf.math.log( gen_probs / probs ))
        return kld

    @tf.function
    def sampling(self, sampling_size):
        data = tf.random.normal((sampling_size, self.input_num), dtype=self.dtype)
        return data, self.probability(data)

    #@tf.function
    def stick_break(self, sampling_size):
        data, probs = self.sampling(sampling_size)
        categories = tf.squeeze(tf.random.categorical(tf.math.log(probs), 1))
        return data, categories

    def fit_categorical(self, train_epoch, data_size, minibatch_size, optimizer, train_ds, test_ds, learninglog):
        train_loss = tf.keras.metrics.Mean(name='train_loss')
        train_accuracy = tf.keras.metrics.CategoricalAccuracy(name='train_accuracy')
        test_loss = tf.keras.metrics.Mean(name='test_loss')
        test_accuracy = tf.keras.metrics.CategoricalAccuracy(name='test_accuracy')

        @tf.function
        def train(input, labels):
            with tf.GradientTape() as tape:
                tape.watch(self.params)
                predict_probs = self.probability(input)
                loss = self._negative_log_likelihood(predict_probs, labels)
            grads = tape.gradient(loss, self.params)
            optimizer.apply_gradients(zip(grads, self.params))
            train_loss(loss)
            train_accuracy(labels, predict_probs)
        
        @tf.function
        def test(input, labels):
            predict_probs = self.probability(input)
            loss = self._negative_log_likelihood(predict_probs, labels)
            test_loss(loss)
            test_accuracy(labels, predict_probs)

        for epoch in range(train_epoch):
            for images, labels in train_ds.shuffle(data_size).batch(minibatch_size):
                train(images, labels)
            for test_images, test_labels in test_ds:
                test(test_images, test_labels)

            template = 'Epoch {}, Loss: {}, Accuracy: {}, Test Loss: {}, Test Accuracy: {}'
            print(template.format(epoch+1, train_loss.result(), train_accuracy.result()*100, test_loss.result(), test_accuracy.result()*100))

            learninglog.make_log(epoch, "train-error", float((1.-train_accuracy.result())))
            learninglog.make_log(epoch, "train-nloglikelihood", float(train_loss.result()))
            learninglog.make_log(epoch, "test-error", float(1.-test_accuracy.result()))
            learninglog.make_log(epoch, "test-nloglikelihood", float(test_loss.result()))

            train_loss.reset_states()
            train_accuracy.reset_states()
            test_loss.reset_states()
            test_accuracy.reset_states()
    
    def fit_generative(self, train_epoch, data_size, minibatch_size, optimizer, train_ds, gen_drbm, learninglog):
        train_loss = tf.keras.metrics.Mean(name='train_loss')

        @tf.function
        def train(input, labels):
            with tf.GradientTape() as tape:
                tape.watch(self.params)
                predict_probs = self.probability(input)
                loss = self._negative_log_likelihood(predict_probs, labels)
            grads = tape.gradient(loss, self.params)
            optimizer.apply_gradients(zip(grads, self.params))
            train_loss(loss)
        
        for epoch in range(train_epoch):
            for images, labels in train_ds.shuffle(data_size).batch(minibatch_size):
                train(images, labels)
            kld = self._kl_divergence(gen_drbm)

            template = 'Epoch {}, Loss: {}, KL-Divergence: {}'
            print(template.format(epoch+1, train_loss.result(), kld))

            learninglog.make_log(epoch, "kl-divergence", float(kld))
            learninglog.make_log(epoch, "nloglikelihood", float(train_loss.result()))

            train_loss.reset_states()

    def save(self, filename):
        data_names = ["input_num", "hidden_num", "output_num", "dtype", "activation", "enable_sparse"]
        param_names = ["b1", "b2", "w1", "w2"]
        if self.enable_sparse:
            param_names.append("sparse")
        data = {}
        for i in data_names:
            data[i] = getattr(self, i)
        data["params"] = {}
        for i in param_names:
            data["params"][i] = getattr(self, i).numpy().tolist()
        json.dump(data, open(filename, "w+"), indent=2)

    @staticmethod
    def load(filename):
        data = json.load(open(filename, "r"))
        enable_sparse = "sparse" in data["params"]
        drbm = DRBM(data["input_num"], data["hidden_num"], data["output_num"], data["activation"], data["dtype"])
        for i in ["b1", "b2", "w1", "w2"]:
            setattr(drbm, i, tf.Variable(data["params"][i], dtype=data["dtype"], name=i))
        drbm.params = [drbm.b1, drbm.b2, drbm.w1, drbm.w2]

        if enable_sparse:
            drbm.sparse = tf.Variable(data["params"]["sparse"], dtype=data["dtype"], name="sparse")
            drbm.params.append(drbm.sparse)
        return drbm